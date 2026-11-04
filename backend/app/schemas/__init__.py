"""Pydantic request/response schemas (also drive the OpenAPI contract)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- auth
class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    title: str | None = None
    permissions: list[str] = []
    patient_id: str | None = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


# --------------------------------------------------------------------------- check-ins
class CheckinSubmit(BaseModel):
    answers: dict[str, Any] = Field(description="Map of question key → answer. See GET checkin-questions.")


class RuleResult(BaseModel):
    rule_id: str
    name: str
    severity: str
    evidence: list[dict]
    response_minutes: int
    assigned_team: str


class CheckinResult(BaseModel):
    checkin_id: str
    recovery_day: int
    risk_level: Literal["GREEN", "AMBER", "RED"]
    rules_triggered: list[RuleResult]
    alerts_created: list[str]
    patient_message: str
    emergency: bool


# --------------------------------------------------------------------------- medications
class MedicationEventCreate(BaseModel):
    status: Literal["TAKEN", "MISSED", "SKIPPED", "UNKNOWN"]
    scheduled_for: datetime | None = None
    note: str | None = Field(default=None, max_length=500)


# --------------------------------------------------------------------------- appointments
class AppointmentCreate(BaseModel):
    appointment_type: str = Field(max_length=60)
    provider_name: str = Field(max_length=200)
    location: str = Field(max_length=300)
    scheduled_at: datetime
    duration_minutes: int = Field(default=30, ge=5, le=480)


class TransportationUpdate(BaseModel):
    status: Literal["CONFIRMED", "NEEDS_HELP"]
    note: str | None = Field(default=None, max_length=500)


class TransportRequestCreate(BaseModel):
    kind: Literal["HOSPITAL_PICKUP", "HELP_FINDING_RIDE"]
    pickup_address: str | None = Field(default=None, max_length=300)
    requested_pickup_at: datetime | None = None
    return_trip: bool = True
    mobility_needs: list[Literal["WALKER", "WHEELCHAIR", "CANE", "STEP_HELP"]] = []
    companion: bool = False
    note: str | None = Field(default=None, max_length=500)


class TransportSchedule(BaseModel):
    mode: Literal["HOSPITAL_SHUTTLE", "NEMT", "RIDESHARE", "VOLUNTEER"]
    vendor: str | None = Field(default=None, max_length=120)
    pickup_at: datetime
    vehicle: str | None = Field(default=None, max_length=120)
    driver_name: str | None = Field(default=None, max_length=120)
    contact_phone: str | None = Field(default=None, max_length=40)
    confirmation_code: str | None = Field(default=None, max_length=40)


class TransportCancel(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


# --------------------------------------------------------------------------- wellbeing & surveys
class MoodCreate(BaseModel):
    mood: Literal["GREAT", "GOOD", "OKAY", "LOW", "BAD"]
    feelings: list[str] = Field(default=[], max_length=9)
    note: str | None = Field(default=None, max_length=500)
    contact_me: bool = False


class SurveySubmit(BaseModel):
    answers: dict[str, int]


class MedicationGuidance(BaseModel):
    missed_dose_guidance: str = Field(min_length=10, max_length=1000)


# --------------------------------------------------------------------------- AI
class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    patient_id: str | None = None


class Citation(BaseModel):
    title: str
    section: str
    version: int | None = None
    authority: str | None = None
    doc_type: str | None = None
    approved_by: str | None = None
    score: float | None = None
    excerpt: str | None = None
    document_id: str | None = None
    document_key: str | None = None


class ChatResponse(BaseModel):
    answer: str
    safety_level: Literal["GREEN", "AMBER", "RED"]
    intent: str
    answered_from_content: bool
    emergency: bool
    citations: list[Citation]
    retrieval: dict
    actions: list[str]
    alert_id: str | None
    model: str | None
    provider: str | None
    prompt_version: str
    latency_ms: int
    flags: list[str]
    message_id: str | None
    disclaimer: str = ("Recovery Companion explains your approved instructions only. It does not diagnose or "
                       "change treatment. In an emergency call 911.")


# --------------------------------------------------------------------------- alerts
class AlertNote(BaseModel):
    note: str | None = Field(default=None, max_length=4000)


class AlertContact(BaseModel):
    method: Literal["PHONE", "SMS", "VIDEO", "IN_APP"]
    outcome: Literal["REACHED", "NO_ANSWER", "LEFT_VOICEMAIL", "WRONG_NUMBER"]
    note: str | None = Field(default=None, max_length=4000)


class AlertResolve(BaseModel):
    resolution: str = Field(min_length=3, max_length=4000)
    outcome: str | None = Field(default=None, max_length=60)


class AlertEscalate(BaseModel):
    to_role: Literal["SURGEON", "NURSE"] = "SURGEON"
    reason: str = Field(min_length=3, max_length=4000)


class EscalationRespond(BaseModel):
    response_note: str = Field(min_length=3, max_length=4000)
    complete: bool = True


class CareTeamMessage(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class NoteCreate(BaseModel):
    note: str = Field(min_length=1, max_length=4000)
    alert_id: str | None = None


# --------------------------------------------------------------------------- caregivers
class CaregiverAuthorize(BaseModel):
    caregiver_email: EmailStr
    relationship_to_patient: str = Field(max_length=60)
    scopes: list[Literal["RECOVERY_STATUS", "TASKS", "REMINDERS", "PROGRESS", "APPOINTMENTS"]]


# --------------------------------------------------------------------------- documents / protocols
class DocumentCreate(BaseModel):
    document_key: str = Field(pattern=r"^[a-z0-9][a-z0-9\-_.]{2,79}$")
    title: str = Field(max_length=300)
    doc_type: Literal["DISCHARGE_INSTRUCTIONS", "RECOVERY_PROTOCOL", "EDUCATION", "MEDICATION_INSTRUCTIONS", "FAQ",
                      "PROCEDURE_PROTOCOL"]
    authority: Literal["SURGEON_APPROVED", "HOSPITAL_APPROVED", "PROGRAM_APPROVED"]
    author: str = Field(max_length=200)
    procedure_type: str = Field(default="ALL", max_length=40)
    patient_population: str = Field(default="Adult post-surgical", max_length=120)
    effective_date: date | None = None
    expiry_date: date | None = None
    content: str = Field(min_length=20, max_length=200_000)


class DocumentSearch(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    procedure_type: str | None = None


class ProtocolCreate(BaseModel):
    rule_id: str = Field(pattern=r"^[A-Z0-9\-]{3,60}$")
    name: str = Field(max_length=200)
    description: str = ""
    procedure_type: str = "ALL"
    severity: Literal["RED", "AMBER"]
    category: str = "CLINICAL"
    condition: dict
    response_minutes: int = Field(ge=5, le=10080)
    assigned_team: Literal["NURSE", "SURGEON", "COORDINATOR"] = "NURSE"
    patient_message: str = ""


class PlanVersionCreate(BaseModel):
    content: dict
    change_summary: str = Field(min_length=3, max_length=1000)


# --------------------------------------------------------------------------- admin
class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(max_length=200)
    role: Literal["PATIENT", "CAREGIVER", "NURSE", "SURGEON", "ADMIN"]
    password: str = Field(min_length=10, max_length=200)
    title: str | None = None


class ProgramCreate(BaseModel):
    name: str = Field(max_length=200)
    description: str = ""
    procedure_types: list[str] = []
    duration_days: int = Field(default=30, ge=7, le=180)
    targets: dict = {}
