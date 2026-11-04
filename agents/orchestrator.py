"""AI Recovery Assistant orchestrator — a controlled, deterministic workflow.

    question
      → Intake/Context Agent            (patient, episode, day, meds)
      → Safety classifier (rules)       GREEN / AMBER / RED + intent
      → RED?  emergency template + RED alert. STOP (no LLM).
      → Medication Safety Agent         dose change / missed dose
      → Knowledge Retrieval Agent       approved, active, in-date chunks only
      → Patient Education Agent         routed LLM, JSON-constrained, grounded
      → Response validation             citations, numbers, forbidden content
      → Citation generation
      → Audit logging (every path)

The LLM is only ever asked to *phrase* an answer from supplied approved text.
It cannot change the safety level, create or suppress alerts, or pick sources.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.alerting import AlertEscalationAgent
from agents.context import IntakeContextAgent, PatientContext
from agents.knowledge import KnowledgeRetrievalAgent, PatientEducationAgent, sources_from_retrieval
from agents.medication_safety import (
    DOSE_CHANGE_MESSAGE, NO_GUIDANCE_MESSAGE, identify_medication, medication_sources,
)
from ai.prompts import PROMPT_VERSION
from ai.router import ModelRouter, get_router
from app.core.observability import metrics
from app.models import Conversation, Message, Patient, User
from app.services import audit
from rules.safety import EMERGENCY_MESSAGE, STANDARD_LIMITATION, SafetyAssessment, classify

NOT_FOUND_MESSAGE = ("I couldn't find this in your approved recovery instructions. Please contact your care team. "
                     "I've passed your question to them so someone can follow up.")
INJECTION_MESSAGE = ("I can only help with questions about your approved recovery instructions, and I can't change "
                     "how I work or the safety rules I follow. " + STANDARD_LIMITATION)
GREETING_MESSAGE = ("Hello! I can answer questions using your approved recovery instructions — for example "
                    "\"When can I shower?\" or \"What exercises are in my plan?\". "
                    "If you feel unwell, please use the daily check-in or call your care team.")


@dataclass
class AssistantReply:
    answer: str
    safety_level: str
    intent: str
    answered_from_content: bool
    citations: list[dict] = field(default_factory=list)
    retrieval: dict = field(default_factory=dict)
    emergency: bool = False
    actions: list[str] = field(default_factory=list)
    alert_id: str | None = None
    model: str | None = None
    provider: str | None = None
    prompt_version: str = PROMPT_VERSION
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    flags: list[str] = field(default_factory=list)
    route: dict = field(default_factory=dict)
    validation_issues: list[str] = field(default_factory=list)
    message_id: str | None = None
    conversation_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class RecoveryAssistantOrchestrator:
    def __init__(self, router: ModelRouter | None = None):
        self.router = router or get_router()
        self.context = IntakeContextAgent()
        self.alerting = AlertEscalationAgent()
        self.knowledge = KnowledgeRetrievalAgent()
        self.education = PatientEducationAgent(self.router)

    # ------------------------------------------------------------------ entry point
    def ask(self, db: Session, actor: User, patient: Patient, question: str) -> AssistantReply:
        started = time.perf_counter()
        question = (question or "").strip()[:1000]
        ctx = self.context.load(db, patient)
        assessment = classify(question)
        metrics.inc("ai_questions", safety=assessment.level, intent=assessment.intent)

        if assessment.level == "RED":
            reply = self._emergency(db, actor, ctx, question, assessment)
        elif assessment.intent in ("DOSE_CHANGE", "MISSED_DOSE"):
            reply = self._medication_dose(db, actor, ctx, question, assessment)
        elif "PROMPT_INJECTION" in assessment.flags:
            reply = AssistantReply(INJECTION_MESSAGE, assessment.level, assessment.intent, False,
                                   flags=assessment.flags, actions=["Request refused: attempted instruction override"])
        elif assessment.intent == "GREETING":
            reply = AssistantReply(GREETING_MESSAGE, "GREEN", "GREETING", False)
        elif assessment.intent == "DIAGNOSIS_REQUEST":
            reply = self._diagnosis(db, actor, ctx, question, assessment)
        elif assessment.intent == "SYMPTOM_REPORT":
            reply = self._symptom(db, actor, ctx, question, assessment)
        elif assessment.intent == "MEDICATION_QUESTION":
            reply = self._grounded(db, actor, ctx, question, assessment, include_medications=True)
        else:
            reply = self._grounded(db, actor, ctx, question, assessment)

        reply.flags = sorted(set(reply.flags) | set(assessment.flags))
        reply.latency_ms = reply.latency_ms or int((time.perf_counter() - started) * 1000)
        self._persist(db, actor, patient, question, reply, assessment)
        metrics.observe("ai_request_ms", (time.perf_counter() - started) * 1000, intent=reply.intent)
        return reply

    # ------------------------------------------------------------------ paths
    def _emergency(self, db, actor, ctx: PatientContext, question, a: SafetyAssessment) -> AssistantReply:
        alert = self.alerting.from_policy(
            db, ctx.patient, "AI-RED-EMERGENCY", f"Emergency symptoms reported to assistant: {', '.join(a.matched_terms)}",
            [{"fact": "assistant_message_terms", "actual": a.matched_terms}], actor=actor,
            episode_id=ctx.episode.id if ctx.episode else None, dedupe_open=False)
        route = self.router.route("EMERGENCY", "RED").to_dict()
        return AssistantReply(EMERGENCY_MESSAGE, "RED", "EMERGENCY", False, emergency=True, alert_id=str(alert.id),
                              actions=["Emergency guidance shown", "RED alert sent to nurse (15 min response)"],
                              route=route, model=None, provider="rules-engine")

    def _medication_dose(self, db, actor, ctx: PatientContext, question, a: SafetyAssessment) -> AssistantReply:
        if a.intent == "MISSED_DOSE":
            match = identify_medication(question, ctx.medications)
            med = match.medication
            if med and med.missed_dose_guidance:
                citation = {"document_id": None, "document_key": f"medication:{med.id}",
                            "title": f"Approved missed-dose guidance: {med.name}", "version": 1,
                            "section": "Missed dose", "authority": "SURGEON_APPROVED", "doc_type": "MEDICATION_RECORD",
                            "approved_by": med.guidance_approved_by, "score": 1.0,
                            "excerpt": med.missed_dose_guidance}
                answer = f"Your approved instructions for {med.name} say: \"{med.missed_dose_guidance}\""
                return AssistantReply(answer, "AMBER", "MISSED_DOSE", True, citations=[citation],
                                      provider="rules-engine", model=None,
                                      route={"task": "MISSED_DOSE", "reason": "Verbatim approved guidance; no LLM"},
                                      actions=["Returned approved missed-dose guidance only"])
            summary = (f"Missed-dose question — no approved guidance for {med.name}" if med else
                       "Missed-dose question — medication not identified" + (" (ambiguous)" if match.ambiguous else ""))
            alert = self.alerting.from_policy(db, ctx.patient, "AI-MED-DOSE-QUESTION", summary,
                                              [{"fact": "patient_question", "actual": question}], actor=actor,
                                              episode_id=ctx.episode.id if ctx.episode else None, dedupe_open=False)
            return AssistantReply(NO_GUIDANCE_MESSAGE, "AMBER", "MISSED_DOSE", False, alert_id=str(alert.id),
                                  provider="rules-engine", actions=["Doctor task created (4 h response)"])
        alert = self.alerting.from_policy(db, ctx.patient, "AI-MED-DOSE-QUESTION",
                                          "Patient asked about changing a medication dose",
                                          [{"fact": "patient_question", "actual": question}], actor=actor,
                                          episode_id=ctx.episode.id if ctx.episode else None, dedupe_open=False)
        return AssistantReply(DOSE_CHANGE_MESSAGE, "AMBER", "DOSE_CHANGE", False, alert_id=str(alert.id),
                              provider="rules-engine", actions=["Dosing advice refused", "Doctor task created (4 h response)"])

    def _diagnosis(self, db, actor, ctx, question, a: SafetyAssessment) -> AssistantReply:
        actions = ["Diagnosis request declined"]
        alert_id = None
        if a.matched_terms:
            alert = self.alerting.from_policy(db, ctx.patient, "AI-AMBER-SYMPTOM",
                                              f"Patient asked about symptoms: {', '.join(a.matched_terms)}",
                                              [{"fact": "patient_question", "actual": question}], actor=actor,
                                              episode_id=ctx.episode.id if ctx.episode else None)
            alert_id = str(alert.id)
            actions.append("Nurse review requested")
        msg = STANDARD_LIMITATION + " You can also complete today's check-in so your care team sees how you're doing."
        return AssistantReply(msg, "AMBER", "DIAGNOSIS_REQUEST", False, alert_id=alert_id, actions=actions,
                              provider="rules-engine")

    def _symptom(self, db, actor, ctx, question, a: SafetyAssessment) -> AssistantReply:
        alert = self.alerting.from_policy(db, ctx.patient, "AI-AMBER-SYMPTOM",
                                          f"Patient reported via assistant: {', '.join(a.matched_terms)}",
                                          [{"fact": "patient_message", "actual": question}], actor=actor,
                                          episode_id=ctx.episode.id if ctx.episode else None)
        grounded = self._grounded(db, actor, ctx, question, a, create_task_if_missing=False)
        lead = ("Thank you for letting us know. I've shared this with your care team and a nurse will review it "
                "(within 4 hours). If it gets much worse, or you have chest pain, trouble breathing or heavy bleeding, "
                "call 911.")
        if grounded.answered_from_content:
            grounded.answer = lead + "\n\nHere is what your approved instructions say:\n" + grounded.answer
        else:
            grounded.answer = lead
        grounded.intent, grounded.safety_level, grounded.alert_id = "SYMPTOM_REPORT", "AMBER", str(alert.id)
        grounded.actions = ["Nurse review requested (AMBER, 4 h)"] + grounded.actions
        return grounded

    def _grounded(self, db, actor, ctx: PatientContext, question, a: SafetyAssessment,
                  include_medications: bool = False, create_task_if_missing: bool = True) -> AssistantReply:
        retrieval = self.knowledge.search(db, question, ctx.procedure_type)
        sources = sources_from_retrieval(retrieval)
        if include_medications and ctx.medications:
            match = identify_medication(question, ctx.medications)
            meds = [match.medication] if match.medication else ctx.medications
            med_sources = medication_sources(meds)
            sources = (med_sources + sources) if match.medication else (sources + med_sources)
            for i, s in enumerate(sources):  # stable ids for the prompt
                s["id"] = f"S{i + 1}"
        result = self.education.answer(question, sources, ctx.prompt_dict(), a.level)
        meta = retrieval.meta() | {"sources_offered": [s["citation"]["title"] + " › " + s["section"] for s in sources]}
        if result.answerable:
            return AssistantReply(result.answer, a.level, a.intent, True, citations=result.citations, retrieval=meta,
                                  model=result.model, provider=result.provider, latency_ms=result.latency_ms,
                                  input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                                  route=result.route, validation_issues=result.validation_issues,
                                  actions=["Answered from approved content"])
        reply = AssistantReply(NOT_FOUND_MESSAGE if create_task_if_missing else "", a.level, a.intent, False,
                               retrieval=meta, model=result.model or None, provider=result.provider or None,
                               route=result.route, validation_issues=result.validation_issues)
        if create_task_if_missing:
            rule = "AI-MED-QUESTION" if include_medications else "AI-UNANSWERED"
            alert = self.alerting.from_policy(db, ctx.patient, rule, f"Unanswered patient question: {question[:200]}",
                                              [{"fact": "patient_question", "actual": question},
                                               {"fact": "retrieval", "actual": retrieval.meta()}],
                                              actor=actor, episode_id=ctx.episode.id if ctx.episode else None,
                                              dedupe_open=False)
            reply.alert_id = str(alert.id)
            reply.actions = ["Not found in approved content — no answer given",
                             ("Doctor" if include_medications else "Care-team") + " task created"]
        return reply

    # ------------------------------------------------------------------ persistence + audit
    def _persist(self, db: Session, actor: User, patient: Patient, question: str, reply: AssistantReply,
                 a: SafetyAssessment) -> None:
        conv = db.scalars(select(Conversation).where(Conversation.patient_id == patient.id,
                                                     Conversation.channel == "ASSISTANT")).first()
        if not conv:
            conv = Conversation(patient_id=patient.id, user_id=actor.id, channel="ASSISTANT")
            db.add(conv)
            db.flush()
        now = datetime.now(timezone.utc)
        conv.last_message_at = now
        db.add(Message(conversation_id=conv.id, patient_id=patient.id, sender_type="PATIENT", sender_user_id=actor.id,
                       content=question, intent=a.intent, safety_level=a.level))
        msg = Message(conversation_id=conv.id, patient_id=patient.id, sender_type="ASSISTANT", content=reply.answer,
                      intent=reply.intent, safety_level=reply.safety_level,
                      answered_from_content=reply.answered_from_content, citations=reply.citations,
                      retrieval_meta=reply.retrieval | {"route": reply.route, "flags": reply.flags,
                                                        "actions": reply.actions,
                                                        "validation_issues": reply.validation_issues},
                      model=reply.model, prompt_version=reply.prompt_version, latency_ms=reply.latency_ms,
                      input_tokens=reply.input_tokens, output_tokens=reply.output_tokens,
                      alert_id=reply.alert_id)
        db.add(msg)
        db.flush()
        reply.message_id, reply.conversation_id = str(msg.id), str(conv.id)
        audit.record(db, "AI_ASSISTANT_RESPONSE", actor=actor, patient_id=patient.id, resource_type="message",
                     resource_id=msg.id, details={
                         "request": question, "response": reply.answer,
                         "safety_classification": a.to_dict(), "final_safety_level": reply.safety_level,
                         "intent": reply.intent, "answered_from_content": reply.answered_from_content,
                         "retrieved_documents": [{k: c.get(k) for k in ("title", "version", "section", "score",
                                                                         "document_key")} for c in reply.citations],
                         "retrieval": reply.retrieval, "model": reply.model, "provider": reply.provider,
                         "prompt_version": reply.prompt_version, "route": reply.route,
                         "rule_triggered": reply.flags, "alert_generated": reply.alert_id,
                         "validation_issues": reply.validation_issues, "latency_ms": reply.latency_ms,
                         "tokens": {"input": reply.input_tokens, "output": reply.output_tokens}})
