"""Model → JSON helpers (kept explicit so no field leaks by accident)."""
from __future__ import annotations

from app.models import (
    Alert, Appointment, Caregiver, Checkin, Document, Medication, Message, Notification, Patient, User,
    WarningProtocol,
)
from app.core.security import ROLE_PERMISSIONS, Role
from app.services.alerts import sla_status


def iso(d):
    return d.isoformat() if d else None


def user_out(u: User, patient_id=None) -> dict:
    return {"id": str(u.id), "email": u.email, "full_name": u.full_name, "role": u.role_name, "title": u.title,
            "permissions": sorted(p.value for p in ROLE_PERMISSIONS[Role(u.role_name)]),
            "patient_id": str(patient_id) if patient_id else None}


def patient_out(p: Patient) -> dict:
    return {"id": str(p.id), "mrn": p.mrn, "first_name": p.first_name, "last_name": p.last_name,
            "full_name": p.full_name, "date_of_birth": iso(p.date_of_birth), "sex": p.sex, "phone": p.phone,
            "email": p.email, "preferred_channel": p.preferred_channel, "enrollment_status": p.enrollment_status,
            "current_risk": p.current_risk, "enrolled_at": iso(p.enrolled_at), "is_synthetic": p.is_synthetic}


def alert_out(a: Alert, include_patient: bool = True) -> dict:
    d = {"id": str(a.id), "patient_id": str(a.patient_id), "severity": a.severity, "category": a.category,
         "source": a.source, "rule_id": a.rule_id, "trigger": a.trigger_summary, "evidence": a.evidence,
         "status": a.status, "required_response_minutes": a.required_response_minutes, "due_at": iso(a.due_at),
         "assigned_team": a.assigned_team, "assigned_user_id": str(a.assigned_user_id) if a.assigned_user_id else None,
         "created_at": iso(a.created_at), "acknowledged_at": iso(a.acknowledged_at),
         "first_contact_at": iso(a.first_contact_at), "resolved_at": iso(a.resolved_at), "closed_at": iso(a.closed_at),
         "resolution": a.resolution, "sla": sla_status(a), "checkin_id": str(a.checkin_id) if a.checkin_id else None}
    if include_patient:
        d["patient_name"] = a.patient.full_name
    return d


def checkin_out(c: Checkin, include_free_text: bool = True) -> dict:
    return {"id": str(c.id), "checkin_date": iso(c.checkin_date), "recovery_day": c.recovery_day, "status": c.status,
            "submitted_at": iso(c.submitted_at), "risk_level": c.risk_level, "rule_results": c.rule_results,
            "answers": {r.question_key: r.value.get("v") for r in c.responses},
            "concern": c.free_text_concern if include_free_text else None}


def medication_out(m: Medication) -> dict:
    return {"id": str(m.id), "name": m.name, "dose_text": m.dose_text, "indication": m.indication, "route": m.route,
            "frequency": m.frequency, "schedule_times": m.schedule_times, "as_needed": m.as_needed,
            "start_date": iso(m.start_date), "end_date": iso(m.end_date), "instructions": m.instructions,
            "missed_dose_guidance": m.missed_dose_guidance, "guidance_approved_by": m.guidance_approved_by,
            "prescriber": m.prescriber, "is_active": m.is_active}


def appointment_out(a: Appointment) -> dict:
    return {"id": str(a.id), "appointment_type": a.appointment_type, "provider_name": a.provider_name,
            "location": a.location, "scheduled_at": iso(a.scheduled_at), "duration_minutes": a.duration_minutes,
            "status": a.status, "transportation_status": a.transportation_status,
            "transportation_note": a.transportation_note, "reminder_sent_at": iso(a.reminder_sent_at)}


def document_out(d: Document, include_content: bool = False) -> dict:
    out = {"id": str(d.id), "document_key": d.document_key, "version": d.version, "title": d.title,
           "doc_type": d.doc_type, "authority": d.authority, "author": d.author, "approval_status": d.approval_status,
           "approved_by": d.approved_by.full_name if d.approved_by else None, "approved_at": iso(d.approved_at),
           "effective_date": iso(d.effective_date), "expiry_date": iso(d.expiry_date),
           "procedure_type": d.procedure_type, "patient_population": d.patient_population, "is_active": d.is_active,
           "checksum": d.checksum, "created_at": iso(d.created_at), "storage_uri": d.storage_uri}
    if include_content:
        out["content"] = d.content
    return out


def protocol_out(p: WarningProtocol) -> dict:
    return {"id": str(p.id), "rule_id": p.rule_id, "version": p.version, "name": p.name, "description": p.description,
            "procedure_type": p.procedure_type, "severity": p.severity, "category": p.category,
            "condition": p.condition, "response_minutes": p.response_minutes, "assigned_team": p.assigned_team,
            "patient_message": p.patient_message, "status": p.status, "approved_at": iso(p.approved_at)}


def message_out(m: Message) -> dict:
    return {"id": str(m.id), "sender_type": m.sender_type,
            "sender_name": m.sender.full_name if m.sender else ("Recovery Assistant" if m.sender_type == "ASSISTANT"
                                                                else "System"),
            "content": m.content, "intent": m.intent, "safety_level": m.safety_level,
            "answered_from_content": m.answered_from_content, "citations": m.citations,
            "actions": (m.retrieval_meta or {}).get("actions", []), "model": m.model,
            "created_at": iso(m.created_at), "read_at": iso(m.read_at)}


def notification_out(n: Notification) -> dict:
    return {"id": str(n.id), "channel": n.channel, "category": n.category, "title": n.title, "body": n.body,
            "status": n.status, "created_at": iso(n.created_at), "read_at": iso(n.read_at)}


def caregiver_out(c: Caregiver) -> dict:
    return {"id": str(c.id), "user_id": str(c.user_id), "name": c.user.full_name, "email": c.user.email,
            "relationship": c.relationship_to_patient, "status": c.status, "authorized_at": iso(c.authorized_at),
            "revoked_at": iso(c.revoked_at),
            "scopes": [p.scope for p in c.permissions if p.revoked_at is None]}
