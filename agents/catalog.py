"""Catalog of the AI agents and their workflows, served to the admin "AI agents" page.

Each agent declares which audit actions represent its work (`activity`), so the
admin page can show live activity counts straight from the append-only audit trail.
An activity entry may narrow an action by a `details` field, e.g. only assistant
responses whose intent was MISSED_DOSE belong to the Medication Safety Agent.
"""
from __future__ import annotations

GROUNDED_INTENTS = ["RECOVERY_QUESTION", "MEDICATION_QUESTION"]

AGENTS: list[dict] = [
    {
        "id": "orchestrator", "name": "Orchestrator", "module": "agents/orchestrator.py", "kind": "DETERMINISTIC",
        "purpose": "Runs every patient question through a fixed, auditable pipeline and decides which agent handles it.",
        "how_it_works": [
            "Loads patient context, then classifies the question as GREEN / AMBER / RED with an intent.",
            "Routes by code: emergency, medication dose, prompt injection, diagnosis, symptom or recovery question.",
            "Saves the patient and assistant messages (encrypted) and writes one audit event per answer.",
        ],
        "inputs": ["Patient question", "Signed-in user"], "outputs": ["Assistant reply", "Alerts / tasks", "Audit event"],
        "guardrails": ["The LLM never chooses the route or safety level", "Every path is audited"],
        "used_by": ["Patient › Ask the assistant", "POST /api/ai/chat", "POST /api/patients/{id}/questions"],
        "activity": [{"action": "AI_ASSISTANT_RESPONSE"}],
    },
    {
        "id": "context", "name": "Intake / Context", "module": "agents/context.py", "kind": "DETERMINISTIC",
        "purpose": "Assembles the minimum patient context a workflow needs, and nothing more.",
        "how_it_works": [
            "Finds the active surgical episode and procedure type.",
            "Computes the recovery day and phase, and loads the approved plan version and active medications.",
        ],
        "inputs": ["Patient"], "outputs": ["Episode, recovery day & phase, approved plan, medications"],
        "guardrails": ["Only the current patient's data is loaded", "Only APPROVED plan versions are used"],
        "used_by": ["Orchestrator", "Check-in Analysis"],
        "activity": [{"action": "AI_ASSISTANT_RESPONSE"}, {"action": "CHECKIN_SUBMITTED"}],
    },
    {
        "id": "knowledge_retrieval", "name": "Knowledge Retrieval", "module": "agents/knowledge.py",
        "kind": "DETERMINISTIC",
        "purpose": "Finds the approved content sections that answer a question (RAG).",
        "how_it_works": [
            "Embeds the question and scores it against document chunks in pgvector.",
            "Keeps only approved, active, in-date chunks that match the patient's procedure.",
            "Returns the top matches above the minimum score, or reports that nothing was found.",
        ],
        "inputs": ["Question", "Procedure type"], "outputs": ["Ranked approved source chunks with scores"],
        "guardrails": ["Draft, retired or expired content is never returned", "Below-threshold matches are dropped"],
        "used_by": ["Orchestrator (recovery, medication and symptom questions)"],
        "activity": [{"action": "AI_ASSISTANT_RESPONSE", "field": "intent",
                      "values": GROUNDED_INTENTS + ["SYMPTOM_REPORT"]}],
    },
    {
        "id": "patient_education", "name": "Patient Education", "module": "agents/knowledge.py", "kind": "LLM",
        "purpose": "Phrases a plain-language answer using only the approved sources it is given. "
                   "This is the only agent that calls an LLM (Claude by default).",
        "how_it_works": [
            "The ModelRouter picks the configured provider for the PATIENT_CLINICAL_QA task.",
            "The LLM receives the question and <source> blocks and must return JSON: answerable, answer, source_ids.",
            "The validator checks citations, numbers and forbidden language. On failure, or if the LLM is "
            "unavailable, the extractive provider quotes the approved text instead.",
        ],
        "inputs": ["Question", "Approved source chunks"], "outputs": ["Grounded answer with citations"],
        "guardrails": ["Cited sources must be a subset of those supplied", "No diagnosis, dosing or invented numbers",
                       "Falls back to verbatim quotes, never to an unvalidated answer"],
        "used_by": ["Orchestrator (recovery and medication questions)"],
        "activity": [{"action": "AI_ASSISTANT_RESPONSE", "field": "intent", "values": GROUNDED_INTENTS}],
    },
    {
        "id": "medication_safety", "name": "Medication Safety", "module": "agents/medication_safety.py",
        "kind": "DETERMINISTIC",
        "purpose": "Handles missed-dose and dose-change questions without ever giving dosing advice.",
        "how_it_works": [
            "Dose-change requests are always refused and a task for the doctor is created.",
            "Missed-dose questions: identifies the medication and returns its approved missed-dose guidance verbatim.",
            "If the medication is ambiguous or has no approved guidance, refuses and creates a task for the doctor.",
        ],
        "inputs": ["Question", "Active medications"], "outputs": ["Verbatim guidance or refusal", "Doctor task"],
        "guardrails": ["No LLM involved", "Never changes a dose or schedule"],
        "used_by": ["Orchestrator (MISSED_DOSE / DOSE_CHANGE intents)"],
        "activity": [{"action": "AI_ASSISTANT_RESPONSE", "field": "intent", "values": ["MISSED_DOSE", "DOSE_CHANGE"]}],
    },
    {
        "id": "checkin_analysis", "name": "Check-in Analysis", "module": "agents/checkin_analysis.py",
        "kind": "DETERMINISTIC",
        "purpose": "Turns a daily check-in into a risk level by running it against approved warning protocols.",
        "how_it_works": [
            "Validates answers against the configured check-in questions.",
            "Builds facts, including trends against previous check-ins and missed-dose history.",
            "Evaluates approved warning protocols with the rules engine, saves the result and raises alerts.",
        ],
        "inputs": ["Check-in answers", "Check-in history"], "outputs": ["Risk level", "Rules triggered", "Alerts"],
        "guardrails": ["Thresholds come only from approved protocols", "No LLM involved"],
        "used_by": ["Patient › Daily check-in", "POST /api/patients/{id}/checkins"],
        "activity": [{"action": "CHECKIN_SUBMITTED"}],
    },
    {
        "id": "alerting", "name": "Alert / Escalation", "module": "agents/alerting.py", "kind": "DETERMINISTIC",
        "purpose": "Converts rule matches and assistant safety findings into care-team work items.",
        "how_it_works": [
            "Picks severity, response time and team from the approved protocol or fixed AI policy.",
            "Creates one alert per check-in (repeat triggers are merged) and notifies the assigned team.",
            "RED alerts also send an SMS to the on-call nurse.",
        ],
        "inputs": ["Rule matches", "AI policy codes"], "outputs": ["Alerts with SLA", "Notifications"],
        "guardrails": ["Severity and SLA never come from an LLM"],
        "used_by": ["Check-in Analysis", "Orchestrator", "Integration Intake", "Scheduled jobs"],
        "activity": [{"action": "ALERT_CREATED"}, {"action": "ALERT_REPEAT_TRIGGER"}],
    },
    {
        "id": "integration_intake", "name": "Integration Intake", "module": "backend/app/services/integrations.py",
        "kind": "DETERMINISTIC",
        "purpose": "Receives EHR (FHIR R4, HL7 v2) and remote-monitoring device data so nobody has to type it in.",
        "how_it_works": [
            "Authenticates the sending system, de-duplicates by message id and parses FHIR, HL7 v2 or device JSON.",
            "Matches the patient by MRN (never auto-enrolls) and updates discharge date, medications and appointments.",
            "Converts readings to canonical units, range-checks them and runs fresh ones through the approved "
            "warning protocols, raising the same care-team alerts as a check-in.",
        ],
        "inputs": ["FHIR Bundle", "HL7 v2 ADT / ORU / SIU", "Device readings"],
        "outputs": ["Updated record", "Device readings", "Alerts / doctor tasks", "HL7 ACK / receipt"],
        "guardrails": ["Thresholds come only from approved protocols", "Readings older than 24 h never alert",
                       "New medications get no missed-dose guidance until the doctor approves it"],
        "used_by": ["Admin › Integrations", "POST /api/integrations/{fhir, hl7v2, devices}"],
        "activity": [{"action": "INTEGRATION_MESSAGE_RECEIVED"}],
    },
    {
        "id": "care_team_summary", "name": "Care-Team Summary", "module": "agents/care_team_summary.py",
        "kind": "DETERMINISTIC",
        "purpose": "Builds a fact-only handoff summary of a patient for nurses and surgeons.",
        "how_it_works": [
            "Reads the latest check-ins, open alerts, medications and appointments.",
            "Formats them as labelled bullets with no inference. "
            "(The ModelRouter supports LLM wording for this task, but the POC keeps it deterministic.)",
        ],
        "inputs": ["Patient record"], "outputs": ["Handoff bullets"],
        "guardrails": ["Shows only what the data says"],
        "used_by": ["Care team › Patient detail", "GET /api/patients/{id}/summary"],
        "activity": [{"action": "PHI_VIEW_SUMMARY"}],
    },
    {
        "id": "recovery_plan", "name": "Recovery Plan", "module": "agents/recovery_plan.py", "kind": "DETERMINISTIC",
        "purpose": "Manages recovery plan versions, four-eyes approval and daily task generation.",
        "how_it_works": [
            "Plans are authored as structured content from procedure templates.",
            "A version must be approved by someone other than its author.",
            "Approval supersedes the previous version and regenerates the patient's daily tasks.",
        ],
        "inputs": ["Plan content", "Approver"], "outputs": ["Approved plan version", "Daily tasks"],
        "guardrails": ["Only APPROVED versions are shown to patients", "Approver ≠ author"],
        "used_by": ["Surgeon › Plan approvals"],
        "activity": [{"action": "PLAN_VERSION_CREATED"}, {"action": "PLAN_VERSION_APPROVED"}],
    },
    {
        "id": "wellbeing", "name": "Wellbeing Companion", "module": "agents/wellbeing.py", "kind": "DETERMINISTIC",
        "purpose": "Asks patients how they feel each time they sign in and answers personally, so the app feels "
                   "like someone is paying attention.",
        "how_it_works": [
            "Shows a mood question (5 faces, optional feelings and note) after every patient sign-in.",
            "Replies using the patient's name, recovery day and plan phase, acknowledges the feelings they picked "
            "and suggests next steps (today's check-in, a ride question, messaging the care team).",
            "Low or bad mood on 3 separate days within 5 days creates an AMBER nurse wellbeing check-in; "
            "'please contact me' creates a nurse task.",
            "A note with emergency or self-harm language raises a RED nurse alert and shows 911 / 988.",
        ],
        "inputs": ["Mood", "Feelings", "Optional note"], "outputs": ["Personal reply", "Nudges", "Nurse tasks"],
        "guardrails": ["Template replies only — no LLM, no medical advice", "Crisis language always escalates"],
        "used_by": ["Patient sign-in", "POST /api/patients/{id}/mood"],
        "activity": [{"action": "MOOD_RECORDED"}],
    },
    {
        "id": "transport", "name": "Transport Coordination", "module": "backend/app/services/transport.py",
        "kind": "DETERMINISTIC",
        "purpose": "Makes sure every patient has a way to get to their follow-up visits, including hospital pickups.",
        "how_it_works": [
            "36 hours before each appointment, asks the patient (in-app + SMS) how they'll get there.",
            "A pickup or help request becomes a coordinator task; booking it tells the patient the pickup time, "
            "vehicle and confirmation code.",
            "Reminds the patient of a booked pickup the day before; no answer 12 h before creates a coordinator task.",
        ],
        "inputs": ["Appointments", "Patient ride requests"], "outputs": ["Ride questions", "Bookings", "Tasks"],
        "guardrails": ["SMS carries no appointment details (PHI-minimal)", "Pickup must be before the visit"],
        "used_by": ["Patient › Appointments", "Care team › Transport", "Scheduled jobs"],
        "activity": [{"action": "TRANSPORT_REQUESTED"}, {"action": "TRANSPORT_SCHEDULED"},
                     {"action": "TRANSPORT_CANCELLED"}],
    },
]

COMPONENTS: list[dict] = [
    {"name": "Safety & intent classifier", "module": "rules/safety.py",
     "purpose": "Labels every question GREEN / AMBER / RED with an intent and flags (e.g. prompt injection) "
                "before any agent or model runs."},
    {"name": "Rules engine", "module": "rules/engine.py",
     "purpose": "Evaluates approved warning-protocol conditions against check-in facts."},
    {"name": "ModelRouter", "module": "ai/router.py",
     "purpose": "Chooses an LLM provider (or none) per task and risk. RED risk never reaches an LLM."},
    {"name": "Response validator", "module": "ai/validation.py",
     "purpose": "Rejects LLM answers with unknown citations, ungrounded numbers or diagnosis/dosing language."},
    {"name": "RAG pipeline", "module": "rag/",
     "purpose": "Chunks and embeds approved documents, and retrieves them with procedure and status filters."},
]

# Flow diagrams. A step is {label, detail, kind, agent?}; kind is one of
# start | step | decision | llm | end. A decision lists its exits in `branches`.
WORKFLOWS: list[dict] = [
    {
        "id": "assistant", "title": "Ask the assistant (POST /api/ai/chat)",
        "summary": "How a patient question becomes a safe, cited answer. Safety decisions are made in code "
                   "before the LLM is involved, and the LLM only phrases text it is handed.",
        "steps": [
            {"label": "Patient asks a question", "kind": "start"},
            {"label": "Load patient context", "kind": "step", "agent": "context",
             "detail": "Episode, recovery day, phase, approved plan, medications"},
            {"label": "Classify safety & intent", "kind": "decision", "detail": "rules/safety.py",
             "branches": [
                 {"when": "RED (emergency)", "outcome": "911 guidance + RED alert to nurse (15 min). No LLM.",
                  "kind": "end", "agent": "alerting"},
                 {"when": "Dose change / missed dose", "outcome": "Verbatim approved guidance, or refuse + doctor task",
                  "kind": "end", "agent": "medication_safety"},
                 {"when": "Prompt injection", "outcome": "Refuse the override attempt", "kind": "end"},
                 {"when": "Diagnosis request", "outcome": "\"I can't diagnose\" (+ nurse review if symptoms)",
                  "kind": "end"},
                 {"when": "Symptom report", "outcome": "AMBER nurse review + relevant approved guidance",
                  "kind": "end", "agent": "alerting"},
                 {"when": "Recovery / medication question", "outcome": "Continue below", "kind": "step"},
             ]},
            {"label": "Retrieve approved content", "kind": "decision", "agent": "knowledge_retrieval",
             "detail": "Approved, active, in-date, procedure-matched chunks",
             "branches": [
                 {"when": "Nothing found", "outcome": "\"Not in your approved instructions\" + care-team task",
                  "kind": "end", "agent": "alerting"},
                 {"when": "Sources found", "outcome": "Continue below", "kind": "step"},
             ]},
            {"label": "Generate grounded answer", "kind": "llm", "agent": "patient_education",
             "detail": "ModelRouter → Claude (JSON schema output)"},
            {"label": "Validate the answer", "kind": "decision", "detail": "ai/validation.py",
             "branches": [
                 {"when": "Fails or LLM unavailable", "outcome": "Extractive answer quoting the same sources",
                  "kind": "step"},
                 {"when": "Passes", "outcome": "Use the LLM answer", "kind": "step"},
             ]},
            {"label": "Attach citations, save messages, write audit event", "kind": "end", "agent": "orchestrator"},
        ],
    },
    {
        "id": "checkin", "title": "Daily check-in",
        "summary": "How a check-in becomes a risk level and, when needed, a care-team alert. No LLM is involved.",
        "steps": [
            {"label": "Patient submits check-in", "kind": "start"},
            {"label": "Validate answers", "kind": "step", "agent": "checkin_analysis",
             "detail": "Against the configured questions for the procedure"},
            {"label": "Build facts", "kind": "step", "agent": "checkin_analysis",
             "detail": "Pain trend vs. previous check-ins, missed doses, recovery day"},
            {"label": "Evaluate approved warning protocols", "kind": "decision", "detail": "rules/engine.py",
             "branches": [
                 {"when": "RED match", "outcome": "RED alert + SMS to on-call nurse; patient told care team will call",
                  "kind": "end", "agent": "alerting"},
                 {"when": "AMBER match", "outcome": "AMBER alert to the assigned team with SLA", "kind": "end",
                  "agent": "alerting"},
                 {"when": "No match", "outcome": "GREEN; encouragement and today's tasks", "kind": "end"},
             ]},
            {"label": "Refresh patient risk, write audit event", "kind": "end", "agent": "checkin_analysis"},
        ],
    },
    {
        "id": "wellbeing", "title": "Mood at sign-in (POST /api/patients/{id}/mood)",
        "summary": "Every patient sign-in starts with a short, optional question about how they feel.",
        "steps": [
            {"label": "Patient signs in", "kind": "start"},
            {"label": "How are you feeling today?", "kind": "step", "agent": "wellbeing",
             "detail": "5 faces, optional feelings, optional note, 'please contact me'"},
            {"label": "Safety check on the note", "kind": "decision", "detail": "rules/safety.py classifier",
             "branches": [{"when": "Emergency / self-harm language", "outcome": "RED nurse alert, show 911 / 988",
                           "kind": "end", "agent": "alerting"},
                          {"when": "Safe", "outcome": "Continue below", "kind": "step"}]},
            {"label": "Trend check", "kind": "decision", "detail": "Low or bad on 3 days within 5 days",
             "branches": [{"when": "Yes", "outcome": "AMBER nurse wellbeing check-in", "kind": "step",
                           "agent": "alerting"},
                          {"when": "No", "outcome": "Continue below", "kind": "step"}]},
            {"label": "Personal reply + next steps", "kind": "end",
             "detail": "Name, recovery day, phase, feelings → check-in / ride / message nudges"},
        ],
    },
    {
        "id": "transport", "title": "Ride to an appointment",
        "summary": "The day before a visit the program makes sure the patient can get there.",
        "steps": [
            {"label": "Appointment within 36 h", "kind": "start", "agent": "transport"},
            {"label": "Ask the patient (in-app + SMS)", "kind": "decision",
             "branches": [{"when": "Own ride", "outcome": "Confirmed", "kind": "end"},
                          {"when": "Hospital pickup / need help", "outcome": "Coordinator task", "kind": "step",
                           "agent": "alerting"},
                          {"when": "No answer 12 h before", "outcome": "Coordinator task", "kind": "step"}]},
            {"label": "Coordinator books the ride", "kind": "step",
             "detail": "Shuttle, medical transport van, rideshare or volunteer; pickup time, vehicle, code"},
            {"label": "Patient told + reminded the day before", "kind": "end"},
        ],
    },
    {
        "id": "routing", "title": "Model routing (ai/router.py)",
        "summary": "Which model, if any, may be used for each task.",
        "steps": [
            {"label": "Task + risk level", "kind": "start"},
            {"label": "ModelRouter decision", "kind": "decision",
             "branches": [
                 {"when": "RED risk or EMERGENCY", "outcome": "No LLM: rules engine, template, human escalation",
                  "kind": "end"},
                 {"when": "PATIENT_CLINICAL_QA", "outcome": "Configured provider (Claude) + RAG + validation",
                  "kind": "llm"},
                 {"when": "Low-risk (e.g. CARE_TEAM_SUMMARY)", "outcome": "Any configured provider", "kind": "llm"},
                 {"when": "Provider missing / error / refusal", "outcome": "Extractive provider (offline, verbatim)",
                  "kind": "step"},
             ]},
        ],
    },
]


def _matches(entry: dict, action: str, details: dict | None) -> bool:
    if entry["action"] != action:
        return False
    return "field" not in entry or (details or {}).get(entry["field"]) in entry["values"]


def agents_for(action: str, details: dict | None) -> list[str]:
    return [a["id"] for a in AGENTS if any(_matches(e, action, details) for e in a["activity"])]
