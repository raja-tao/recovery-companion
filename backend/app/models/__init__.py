"""SQLAlchemy ORM models. See docs/DATABASE.md for the ER overview."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import get_settings
from app.core.database import Base
from app.core.security import EncryptedText
from app.models.base import Timestamps, UUIDPk, utcnow

JSONType = JSON().with_variant(JSONB(), "postgresql")
FK = lambda target, **kw: ForeignKey(target, ondelete=kw.pop("ondelete", "CASCADE"), **kw)  # noqa: E731


# =========================================================================== identity
class RoleModel(UUIDPk, Timestamps, Base):
    __tablename__ = "roles"
    name: Mapped[str] = mapped_column(String(32), unique=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    permissions: Mapped[list] = mapped_column(JSONType, default=list)


class User(UUIDPk, Timestamps, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(200))
    role_id: Mapped[uuid.UUID] = mapped_column(FK("roles.id", ondelete="RESTRICT"), index=True)
    title: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(40))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    role: Mapped[RoleModel] = relationship(lazy="joined")

    @property
    def role_name(self) -> str:
        return self.role.name


class Program(UUIDPk, Timestamps, Base):
    __tablename__ = "programs"
    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    procedure_types: Mapped[list] = mapped_column(JSONType, default=list)
    duration_days: Mapped[int] = mapped_column(Integer, default=30)
    targets: Mapped[dict] = mapped_column(JSONType, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Patient(UUIDPk, Timestamps, Base):
    __tablename__ = "patients"
    user_id: Mapped[uuid.UUID | None] = mapped_column(FK("users.id", ondelete="SET NULL"), unique=True)
    program_id: Mapped[uuid.UUID | None] = mapped_column(FK("programs.id", ondelete="SET NULL"), index=True)
    mrn: Mapped[str] = mapped_column(String(40), unique=True)  # synthetic identifier
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    date_of_birth: Mapped[date] = mapped_column(Date)
    sex: Mapped[str | None] = mapped_column(String(20))
    phone: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(255))
    preferred_channel: Mapped[str] = mapped_column(String(20), default="IN_APP")
    preferred_language: Mapped[str] = mapped_column(String(20), default="en")
    assigned_nurse_id: Mapped[uuid.UUID | None] = mapped_column(FK("users.id", ondelete="SET NULL"), index=True)
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    enrollment_status: Mapped[str] = mapped_column(String(20), default="ACTIVE", index=True)
    current_risk: Mapped[str] = mapped_column(String(10), default="GREEN", index=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


class Caregiver(UUIDPk, Timestamps, Base):
    """Authorization of a caregiver user for a specific patient."""
    __tablename__ = "caregivers"
    __table_args__ = (UniqueConstraint("user_id", "patient_id", name="uq_caregiver_patient"),)
    user_id: Mapped[uuid.UUID] = mapped_column(FK("users.id"), index=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(FK("patients.id"), index=True)
    relationship_to_patient: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", index=True)  # ACTIVE | REVOKED
    authorized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped[User] = relationship(lazy="joined", foreign_keys=[user_id])
    permissions: Mapped[list["CaregiverPermission"]] = relationship(back_populates="caregiver", lazy="selectin",
                                                                   cascade="all, delete-orphan")


class CaregiverPermission(UUIDPk, Timestamps, Base):
    __tablename__ = "caregiver_permissions"
    __table_args__ = (UniqueConstraint("caregiver_id", "scope", name="uq_caregiver_scope"),)
    caregiver_id: Mapped[uuid.UUID] = mapped_column(FK("caregivers.id"), index=True)
    scope: Mapped[str] = mapped_column(String(40))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    caregiver: Mapped[Caregiver] = relationship(back_populates="permissions")


# =========================================================================== episode & plan
class SurgicalEpisode(UUIDPk, Timestamps, Base):
    __tablename__ = "surgical_episodes"
    patient_id: Mapped[uuid.UUID] = mapped_column(FK("patients.id"), index=True)
    program_id: Mapped[uuid.UUID | None] = mapped_column(FK("programs.id", ondelete="SET NULL"))
    procedure_type: Mapped[str] = mapped_column(String(40), index=True)  # e.g. TKA, THA, LAP_CHOLE
    procedure_name: Mapped[str] = mapped_column(String(200))
    surgeon_id: Mapped[uuid.UUID | None] = mapped_column(FK("users.id", ondelete="SET NULL"), index=True)
    hospital: Mapped[str] = mapped_column(String(200))
    surgery_date: Mapped[date] = mapped_column(Date, index=True)
    discharge_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", index=True)
    surgeon: Mapped[User | None] = relationship(lazy="joined", foreign_keys=[surgeon_id])


class RecoveryPlan(UUIDPk, Timestamps, Base):
    __tablename__ = "recovery_plans"
    patient_id: Mapped[uuid.UUID] = mapped_column(FK("patients.id"), index=True)
    episode_id: Mapped[uuid.UUID] = mapped_column(FK("surgical_episodes.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")


class RecoveryPlanVersion(UUIDPk, Timestamps, Base):
    __tablename__ = "recovery_plan_versions"
    __table_args__ = (UniqueConstraint("plan_id", "version", name="uq_plan_version"),)
    plan_id: Mapped[uuid.UUID] = mapped_column(FK("recovery_plans.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    # DRAFT | PENDING_APPROVAL | APPROVED | SUPERSEDED | REJECTED
    status: Mapped[str] = mapped_column(String(24), default="DRAFT", index=True)
    content: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(FK("users.id", ondelete="SET NULL"))
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(FK("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    change_summary: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[User | None] = relationship(lazy="joined", foreign_keys=[created_by_id])
    approved_by: Mapped[User | None] = relationship(lazy="joined", foreign_keys=[approved_by_id])


class RecoveryTask(UUIDPk, Timestamps, Base):
    __tablename__ = "recovery_tasks"
    plan_version_id: Mapped[uuid.UUID] = mapped_column(FK("recovery_plan_versions.id"), index=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(FK("patients.id"), index=True)
    day_from: Mapped[int] = mapped_column(Integer)
    day_to: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(30))  # ACTIVITY | WALKING | WOUND | HYDRATION | PT | CHECKIN
    title: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str] = mapped_column(Text, default="")
    caregiver_visible: Mapped[bool] = mapped_column(Boolean, default=True)


class TaskCompletion(UUIDPk, Timestamps, Base):
    __tablename__ = "task_completions"
    __table_args__ = (UniqueConstraint("task_id", "for_date", name="uq_task_day"),)
    task_id: Mapped[uuid.UUID] = mapped_column(FK("recovery_tasks.id"), index=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(FK("patients.id"), index=True)
    for_date: Mapped[date] = mapped_column(Date)
    completed_by_id: Mapped[uuid.UUID | None] = mapped_column(FK("users.id", ondelete="SET NULL"))


# =========================================================================== check-ins
class CheckinQuestion(UUIDPk, Timestamps, Base):
    __tablename__ = "checkin_questions"
    __table_args__ = (UniqueConstraint("procedure_type", "key", name="uq_question_proc_key"),)
    procedure_type: Mapped[str] = mapped_column(String(40), default="ALL", index=True)
    key: Mapped[str] = mapped_column(String(60))
    text: Mapped[str] = mapped_column(String(300))
    answer_type: Mapped[str] = mapped_column(String(20))  # SCALE | CHOICE | MULTI | NUMBER | BOOLEAN | TEXT
    options: Mapped[list] = mapped_column(JSONType, default=list)
    min_value: Mapped[float | None] = mapped_column(Float)
    max_value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(20))
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    help_text: Mapped[str | None] = mapped_column(String(300))


class Checkin(UUIDPk, Timestamps, Base):
    __tablename__ = "checkins"
    __table_args__ = (Index("ix_checkins_patient_date", "patient_id", "checkin_date"),)
    patient_id: Mapped[uuid.UUID] = mapped_column(FK("patients.id"), index=True)
    episode_id: Mapped[uuid.UUID] = mapped_column(FK("surgical_episodes.id"))
    checkin_date: Mapped[date] = mapped_column(Date)
    recovery_day: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="COMPLETED")  # COMPLETED | MISSED
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_by_id: Mapped[uuid.UUID | None] = mapped_column(FK("users.id", ondelete="SET NULL"))
    risk_level: Mapped[str] = mapped_column(String(10), default="GREEN", index=True)
    rule_results: Mapped[list] = mapped_column(JSONType, default=list)
    free_text_concern: Mapped[str | None] = mapped_column(EncryptedText)
    responses: Mapped[list["CheckinResponse"]] = relationship(back_populates="checkin", lazy="selectin",
                                                             cascade="all, delete-orphan")


class CheckinResponse(UUIDPk, Timestamps, Base):
    __tablename__ = "checkin_responses"
    checkin_id: Mapped[uuid.UUID] = mapped_column(FK("checkins.id"), index=True)
    question_key: Mapped[str] = mapped_column(String(60))
    value: Mapped[dict] = mapped_column(JSONType)  # {"v": <number|string|bool|list>}
    checkin: Mapped[Checkin] = relationship(back_populates="responses")


# =========================================================================== medications
class Medication(UUIDPk, Timestamps, Base):
    __tablename__ = "medications"
    patient_id: Mapped[uuid.UUID] = mapped_column(FK("patients.id"), index=True)
    episode_id: Mapped[uuid.UUID | None] = mapped_column(FK("surgical_episodes.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(120))
    dose_text: Mapped[str] = mapped_column(String(120))  # display only — never modified by AI
    indication: Mapped[str] = mapped_column(String(120))  # "pain", "blood clot prevention", ...
    route: Mapped[str] = mapped_column(String(40), default="oral")
    frequency: Mapped[str] = mapped_column(String(80))
    schedule_times: Mapped[list] = mapped_column(JSONType, default=list)  # ["08:00","20:00"]
    as_needed: Mapped[bool] = mapped_column(Boolean, default=False)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    instructions: Mapped[str] = mapped_column(Text, default="")
    missed_dose_guidance: Mapped[str | None] = mapped_column(Text)  # approved text or NULL
    guidance_approved_by: Mapped[str | None] = mapped_column(String(200))
    prescriber: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class MedicationEvent(UUIDPk, Timestamps, Base):
    __tablename__ = "medication_events"
    __table_args__ = (Index("ix_med_events_patient_sched", "patient_id", "scheduled_for"),)
    medication_id: Mapped[uuid.UUID] = mapped_column(FK("medications.id"), index=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(FK("patients.id"), index=True)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20))  # TAKEN | MISSED | SKIPPED | UNKNOWN
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    recorded_by_id: Mapped[uuid.UUID | None] = mapped_column(FK("users.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(EncryptedText)


# =========================================================================== appointments
class Appointment(UUIDPk, Timestamps, Base):
    __tablename__ = "appointments"
    patient_id: Mapped[uuid.UUID] = mapped_column(FK("patients.id"), index=True)
    episode_id: Mapped[uuid.UUID | None] = mapped_column(FK("surgical_episodes.id", ondelete="SET NULL"))
    appointment_type: Mapped[str] = mapped_column(String(60))  # POST_OP_VISIT | PT | WOUND_CHECK | LAB
    provider_name: Mapped[str] = mapped_column(String(200))
    location: Mapped[str] = mapped_column(String(300))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    status: Mapped[str] = mapped_column(String(20), default="SCHEDULED", index=True)
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    transportation_status: Mapped[str] = mapped_column(String(20), default="UNKNOWN")  # UNKNOWN|CONFIRMED|NEEDS_HELP
    transportation_note: Mapped[str | None] = mapped_column(EncryptedText)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(FK("users.id", ondelete="SET NULL"))


# =========================================================================== content & RAG
class Document(UUIDPk, Timestamps, Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("document_key", "version", name="uq_document_version"),
                      Index("ix_documents_retrievable", "approval_status", "is_active"))
    document_key: Mapped[str] = mapped_column(String(80), index=True)  # stable across versions
    version: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(300))
    # DISCHARGE_INSTRUCTIONS | RECOVERY_PROTOCOL | EDUCATION | MEDICATION_INSTRUCTIONS | FAQ | PROCEDURE_PROTOCOL
    doc_type: Mapped[str] = mapped_column(String(40))
    authority: Mapped[str] = mapped_column(String(30))  # SURGEON_APPROVED | HOSPITAL_APPROVED | PROGRAM_APPROVED
    author: Mapped[str] = mapped_column(String(200))
    approval_status: Mapped[str] = mapped_column(String(20), default="DRAFT")  # DRAFT|PENDING|APPROVED|REJECTED|RETIRED
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(FK("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_date: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    procedure_type: Mapped[str] = mapped_column(String(40), default="ALL", index=True)
    patient_population: Mapped[str] = mapped_column(String(120), default="Adult post-surgical")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    content: Mapped[str] = mapped_column(Text)
    content_format: Mapped[str] = mapped_column(String(20), default="markdown")
    storage_uri: Mapped[str | None] = mapped_column(String(500))  # S3 URI in AWS
    checksum: Mapped[str] = mapped_column(String(64))
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(FK("users.id", ondelete="SET NULL"))
    approved_by: Mapped[User | None] = relationship(lazy="joined", foreign_keys=[approved_by_id])


class DocumentChunk(UUIDPk, Timestamps, Base):
    __tablename__ = "document_chunks"
    document_id: Mapped[uuid.UUID] = mapped_column(FK("documents.id"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    embedding = mapped_column(Vector(get_settings().embedding_dim))
    embedding_model: Mapped[str] = mapped_column(String(80))
    meta: Mapped[dict] = mapped_column(JSONType, default=dict)
    document: Mapped[Document] = relationship(lazy="joined")


class EducationContent(UUIDPk, Timestamps, Base):
    __tablename__ = "education_content"
    document_id: Mapped[uuid.UUID | None] = mapped_column(FK("documents.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(String(500), default="")
    body: Mapped[str] = mapped_column(Text)
    procedure_type: Mapped[str] = mapped_column(String(40), default="ALL", index=True)
    phase: Mapped[str] = mapped_column(String(20), default="ALL")  # STABILIZE|MONITOR|PROGRESS|TRANSITION|ALL
    reading_minutes: Mapped[int] = mapped_column(Integer, default=3)
    status: Mapped[str] = mapped_column(String(20), default="APPROVED")


# =========================================================================== rules & alerts
class WarningProtocol(UUIDPk, Timestamps, Base):
    __tablename__ = "warning_protocols"
    __table_args__ = (UniqueConstraint("rule_id", "version", name="uq_protocol_version"),)
    rule_id: Mapped[str] = mapped_column(String(60), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    procedure_type: Mapped[str] = mapped_column(String(40), default="ALL")
    severity: Mapped[str] = mapped_column(String(10))  # RED | AMBER
    category: Mapped[str] = mapped_column(String(30), default="CLINICAL")
    condition: Mapped[dict] = mapped_column(JSONType)  # rule DSL — see rules/engine.py
    response_minutes: Mapped[int] = mapped_column(Integer)
    assigned_team: Mapped[str] = mapped_column(String(30), default="NURSE")
    patient_message: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")  # DRAFT|APPROVED|RETIRED
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(FK("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Alert(UUIDPk, Timestamps, Base):
    """A care-team work item. Clinical alerts and care-team tasks (medication
    questions, unanswered questions, transportation) share this table so that a
    single worklist, SLA clock and audit trail covers all of them."""
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_open", "status", "severity", "due_at"),)
    patient_id: Mapped[uuid.UUID] = mapped_column(FK("patients.id"), index=True)
    episode_id: Mapped[uuid.UUID | None] = mapped_column(FK("surgical_episodes.id", ondelete="SET NULL"))
    checkin_id: Mapped[uuid.UUID | None] = mapped_column(FK("checkins.id", ondelete="SET NULL"))
    protocol_id: Mapped[uuid.UUID | None] = mapped_column(FK("warning_protocols.id", ondelete="SET NULL"))
    rule_id: Mapped[str] = mapped_column(String(60), index=True)
    severity: Mapped[str] = mapped_column(String(10), index=True)  # RED | AMBER | INFO
    # CLINICAL | MISSED_CHECKIN | MEDICATION_QUESTION | MEDICATION_ADHERENCE | UNANSWERED_QUESTION
    # | TRANSPORTATION | AI_SAFETY | SYMPTOM_REPORT
    category: Mapped[str] = mapped_column(String(30), index=True)
    source: Mapped[str] = mapped_column(String(30))  # CHECKIN | AI_ASSISTANT | SCHEDULER | APPOINTMENT | MEDICATION
    trigger_summary: Mapped[str] = mapped_column(String(500))
    evidence: Mapped[list] = mapped_column(JSONType, default=list)
    status: Mapped[str] = mapped_column(String(24), default="NEW", index=True)
    required_response_minutes: Mapped[int] = mapped_column(Integer)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    assigned_team: Mapped[str] = mapped_column(String(30), index=True)  # NURSE | SURGEON | COORDINATOR
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(FK("users.id", ondelete="SET NULL"))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by_id: Mapped[uuid.UUID | None] = mapped_column(FK("users.id", ondelete="SET NULL"))
    first_contact_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[str | None] = mapped_column(EncryptedText)
    sla_breached: Mapped[bool] = mapped_column(Boolean, default=False)
    patient: Mapped[Patient] = relationship(lazy="joined")


class Escalation(UUIDPk, Timestamps, Base):
    __tablename__ = "escalations"
    alert_id: Mapped[uuid.UUID] = mapped_column(FK("alerts.id"), index=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(FK("patients.id"), index=True)
    from_user_id: Mapped[uuid.UUID | None] = mapped_column(FK("users.id", ondelete="SET NULL"))
    to_role: Mapped[str] = mapped_column(String(30))
    to_user_id: Mapped[uuid.UUID | None] = mapped_column(FK("users.id", ondelete="SET NULL"), index=True)
    reason: Mapped[str] = mapped_column(EncryptedText)
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)  # OPEN | ACKNOWLEDGED | COMPLETED
    response_note: Mapped[str | None] = mapped_column(EncryptedText)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    from_user: Mapped[User | None] = relationship(lazy="joined", foreign_keys=[from_user_id])


class CareTeamAction(UUIDPk, Timestamps, Base):
    __tablename__ = "care_team_actions"
    patient_id: Mapped[uuid.UUID] = mapped_column(FK("patients.id"), index=True)
    alert_id: Mapped[uuid.UUID | None] = mapped_column(FK("alerts.id", ondelete="SET NULL"), index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(FK("users.id", ondelete="SET NULL"))
    # ACKNOWLEDGE | CONTACT_ATTEMPT | CONTACT_MADE | NOTE | RESOLVE | ESCALATE | CLOSE | MESSAGE | STATUS_CHANGE
    action_type: Mapped[str] = mapped_column(String(30))
    contact_method: Mapped[str | None] = mapped_column(String(20))  # PHONE | SMS | VIDEO | IN_APP
    outcome: Mapped[str | None] = mapped_column(String(60))
    note: Mapped[str | None] = mapped_column(EncryptedText)
    internal: Mapped[bool] = mapped_column(Boolean, default=True)  # internal notes hidden from patient/caregiver
    actor: Mapped[User | None] = relationship(lazy="joined", foreign_keys=[actor_id])


# =========================================================================== comms
class Notification(UUIDPk, Timestamps, Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_status", "user_id", "status"),)
    user_id: Mapped[uuid.UUID | None] = mapped_column(FK("users.id"), index=True)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(FK("patients.id"), index=True)
    channel: Mapped[str] = mapped_column(String(10))  # EMAIL | SMS | IN_APP
    # MEDICATION_REMINDER | CHECKIN_REMINDER | APPOINTMENT_REMINDER | CARE_TEAM_ESCALATION | MISSED_CHECKIN | MESSAGE
    category: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="PENDING")  # PENDING | SENT | FAILED | READ
    provider: Mapped[str] = mapped_column(String(40), default="")
    provider_message_id: Mapped[str | None] = mapped_column(String(120))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dedupe_key: Mapped[str | None] = mapped_column(String(200), unique=True)


class Conversation(UUIDPk, Timestamps, Base):
    __tablename__ = "conversations"
    patient_id: Mapped[uuid.UUID] = mapped_column(FK("patients.id"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(FK("users.id", ondelete="SET NULL"))
    channel: Mapped[str] = mapped_column(String(20), default="ASSISTANT")  # ASSISTANT | CARE_TEAM
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Message(UUIDPk, Timestamps, Base):
    __tablename__ = "messages"
    conversation_id: Mapped[uuid.UUID] = mapped_column(FK("conversations.id"), index=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(FK("patients.id"), index=True)
    sender_type: Mapped[str] = mapped_column(String(20))  # PATIENT | ASSISTANT | CARE_TEAM | SYSTEM
    sender_user_id: Mapped[uuid.UUID | None] = mapped_column(FK("users.id", ondelete="SET NULL"))
    content: Mapped[str] = mapped_column(EncryptedText)
    intent: Mapped[str | None] = mapped_column(String(40))
    safety_level: Mapped[str | None] = mapped_column(String(10))
    answered_from_content: Mapped[bool | None] = mapped_column(Boolean)
    citations: Mapped[list] = mapped_column(JSONType, default=list)
    retrieval_meta: Mapped[dict] = mapped_column(JSONType, default=dict)
    model: Mapped[str | None] = mapped_column(String(80))
    prompt_version: Mapped[str | None] = mapped_column(String(40))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    alert_id: Mapped[uuid.UUID | None] = mapped_column(FK("alerts.id", ondelete="SET NULL"))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sender: Mapped[User | None] = relationship(lazy="joined", foreign_keys=[sender_user_id])


# =========================================================================== integrations
class IntegrationSource(UUIDPk, Timestamps, Base):
    """A system allowed to push data in (EHR interface, device cloud, patient app). Keys are stored hashed."""
    __tablename__ = "integration_sources"
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    channel: Mapped[str] = mapped_column(String(20))  # FHIR | HL7V2 | DEVICE
    description: Mapped[str] = mapped_column(Text, default="")
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    key_prefix: Mapped[str] = mapped_column(String(12))  # first characters, to recognise a key without storing it
    key_rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InboundMessage(UUIDPk, Timestamps, Base):
    """One received message. (source, external_id) makes delivery idempotent."""
    __tablename__ = "inbound_messages"
    __table_args__ = (UniqueConstraint("source_id", "external_id", name="uq_inbound_source_external"),
                      Index("ix_inbound_received", "received_at"))
    source_id: Mapped[uuid.UUID] = mapped_column(FK("integration_sources.id"), index=True)
    channel: Mapped[str] = mapped_column(String(20), index=True)
    message_type: Mapped[str] = mapped_column(String(60))
    external_id: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), index=True)  # RECEIVED → PROCESSED | PARTIAL | REJECTED
    patient_id: Mapped[uuid.UUID | None] = mapped_column(FK("patients.id", ondelete="SET NULL"), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processing_ms: Mapped[int | None] = mapped_column(Integer)
    result: Mapped[dict] = mapped_column(JSONType, default=dict)  # counts, alerts, warnings (no PHI values)
    errors: Mapped[list] = mapped_column(JSONType, default=list)
    payload: Mapped[str | None] = mapped_column(EncryptedText)  # raw message (PHI) — encrypted at rest
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[IntegrationSource] = relationship(lazy="joined")


class DeviceReading(UUIDPk, Timestamps, Base):
    """A normalized vital sign / activity reading from a device, wearable or EHR result feed."""
    __tablename__ = "device_readings"
    __table_args__ = (Index("ix_device_readings_patient_time", "patient_id", "measured_at"),)
    patient_id: Mapped[uuid.UUID] = mapped_column(FK("patients.id"), index=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(FK("inbound_messages.id", ondelete="SET NULL"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # TEMPERATURE | HEART_RATE | SPO2 | BP_* | WEIGHT | STEPS | PAIN_SCORE
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(20))
    code: Mapped[str | None] = mapped_column(String(20))  # LOINC
    device: Mapped[str | None] = mapped_column(String(120))
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    alert_id: Mapped[uuid.UUID | None] = mapped_column(FK("alerts.id", ondelete="SET NULL"))


class PharmacyFill(UUIDPk, Timestamps, Base):
    """A pharmacy fill / pick-up notification (NCPDP SCRIPT RxFill) for one prescription."""
    __tablename__ = "pharmacy_fills"
    __table_args__ = (Index("ix_pharmacy_fills_patient_time", "patient_id", "reported_at"),)
    patient_id: Mapped[uuid.UUID] = mapped_column(FK("patients.id"), index=True)
    medication_id: Mapped[uuid.UUID | None] = mapped_column(FK("medications.id", ondelete="SET NULL"), index=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(FK("inbound_messages.id", ondelete="SET NULL"))
    drug_description: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20))  # DISPENSED | PARTIAL | NOT_DISPENSED | TRANSFERRED
    quantity: Mapped[str | None] = mapped_column(String(40))
    days_supply: Mapped[int | None] = mapped_column(Integer)
    fill_date: Mapped[date | None] = mapped_column(Date)
    pharmacy_name: Mapped[str | None] = mapped_column(String(200))
    reason: Mapped[str | None] = mapped_column(String(300))  # why not dispensed, if given
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    alert_id: Mapped[uuid.UUID | None] = mapped_column(FK("alerts.id", ondelete="SET NULL"))


class OutboundMessage(UUIDPk, Timestamps, Base):
    """A FHIR resource queued for the EHR (alerts as Communication, surveys as QuestionnaireResponse)."""
    __tablename__ = "outbound_messages"
    __table_args__ = (Index("ix_outbound_due", "status", "next_attempt_at"),)
    destination: Mapped[str] = mapped_column(String(40))  # e.g. ehr-fhir
    resource_type: Mapped[str] = mapped_column(String(40))  # Communication | QuestionnaireResponse
    dedupe_key: Mapped[str] = mapped_column(String(120), unique=True)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(FK("patients.id", ondelete="SET NULL"), index=True)
    related_type: Mapped[str | None] = mapped_column(String(40))
    related_id: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[str] = mapped_column(EncryptedText)  # FHIR JSON (PHI) — encrypted at rest
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)  # PENDING | SENT | FAILED
    delivery_mode: Mapped[str | None] = mapped_column(String(20))  # HTTP | SIMULATED
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_error: Mapped[str | None] = mapped_column(String(500))
    response_status: Mapped[int | None] = mapped_column(Integer)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# =========================================================================== wellbeing & outcomes
class MoodEntry(UUIDPk, Timestamps, Base):
    """How the patient says they feel, asked once per sign-in."""
    __tablename__ = "mood_entries"
    __table_args__ = (Index("ix_mood_patient_time", "patient_id", "recorded_at"),)
    patient_id: Mapped[uuid.UUID] = mapped_column(FK("patients.id"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(FK("users.id", ondelete="SET NULL"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    mood: Mapped[str] = mapped_column(String(10))  # GREAT | GOOD | OKAY | LOW | BAD
    score: Mapped[int] = mapped_column(Integer)  # 5 (great) … 1 (bad)
    feelings: Mapped[list] = mapped_column(JSONType, default=list)  # e.g. ["ANXIOUS", "TIRED"]
    note: Mapped[str | None] = mapped_column(EncryptedText)
    context: Mapped[str] = mapped_column(String(20), default="LOGIN")
    alert_id: Mapped[uuid.UUID | None] = mapped_column(FK("alerts.id", ondelete="SET NULL"))


class PromResponse(UUIDPk, Timestamps, Base):
    """A completed patient-reported outcome survey (HOOS JR / KOOS JR) at one time point."""
    __tablename__ = "prom_responses"
    __table_args__ = (UniqueConstraint("patient_id", "instrument", "timepoint", name="uq_prom_timepoint"),)
    patient_id: Mapped[uuid.UUID] = mapped_column(FK("patients.id"), index=True)
    episode_id: Mapped[uuid.UUID | None] = mapped_column(FK("surgical_episodes.id", ondelete="SET NULL"))
    instrument: Mapped[str] = mapped_column(String(20))  # HOOS_JR | KOOS_JR
    timepoint: Mapped[str] = mapped_column(String(20))  # POSTOP_2W | POSTOP_30D
    recovery_day: Mapped[int] = mapped_column(Integer)
    answers: Mapped[dict] = mapped_column(JSONType, default=dict)  # item id → 0..4
    raw_score: Mapped[int] = mapped_column(Integer)
    max_score: Mapped[int] = mapped_column(Integer)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    submitted_by_id: Mapped[uuid.UUID | None] = mapped_column(FK("users.id", ondelete="SET NULL"))


# =========================================================================== transport
class TransportRequest(UUIDPk, Timestamps, Base):
    """A ride to an appointment the program arranges (hospital pickup, NEMT, rideshare)."""
    __tablename__ = "transport_requests"
    appointment_id: Mapped[uuid.UUID] = mapped_column(FK("appointments.id"), index=True)
    patient_id: Mapped[uuid.UUID] = mapped_column(FK("patients.id"), index=True)
    # REQUESTED → SCHEDULED → COMPLETED, or CANCELLED
    status: Mapped[str] = mapped_column(String(20), default="REQUESTED", index=True)
    kind: Mapped[str] = mapped_column(String(20))  # HOSPITAL_PICKUP | HELP_FINDING_RIDE
    pickup_address: Mapped[str | None] = mapped_column(EncryptedText)
    requested_pickup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    return_trip: Mapped[bool] = mapped_column(Boolean, default=True)
    mobility_needs: Mapped[list] = mapped_column(JSONType, default=list)  # WALKER | WHEELCHAIR | CANE | STEP_HELP
    companion: Mapped[bool] = mapped_column(Boolean, default=False)
    patient_note: Mapped[str | None] = mapped_column(EncryptedText)
    mode: Mapped[str | None] = mapped_column(String(20))  # HOSPITAL_SHUTTLE | NEMT | RIDESHARE | VOLUNTEER
    vendor: Mapped[str | None] = mapped_column(String(120))
    pickup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    vehicle: Mapped[str | None] = mapped_column(String(120))
    driver_name: Mapped[str | None] = mapped_column(String(120))
    contact_phone: Mapped[str | None] = mapped_column(String(40))
    confirmation_code: Mapped[str | None] = mapped_column(String(40))
    arranged_by_id: Mapped[uuid.UUID | None] = mapped_column(FK("users.id", ondelete="SET NULL"))
    arranged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_reason: Mapped[str | None] = mapped_column(String(300))
    alert_id: Mapped[uuid.UUID | None] = mapped_column(FK("alerts.id", ondelete="SET NULL"))


# =========================================================================== audit
class AuditEvent(UUIDPk, Base):
    """Append-only. UPDATE/DELETE are blocked by a database trigger."""
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_patient_time", "patient_id", "occurred_at"),)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    actor_role: Mapped[str | None] = mapped_column(String(20))
    actor_email: Mapped[str | None] = mapped_column(String(255))
    patient_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(String(60), index=True)
    resource_type: Mapped[str | None] = mapped_column(String(40))
    resource_id: Mapped[str | None] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(20), default="SUCCESS")
    details: Mapped[dict] = mapped_column(JSONType, default=dict)
    request_id: Mapped[str | None] = mapped_column(String(64))
    ip_address: Mapped[str | None] = mapped_column(String(64))
