"""Recovery Plan Agent — deterministic plan assembly, versioning and approval.

Plans are authored as structured content (by clinicians/admins, seeded from
procedure templates). Only APPROVED versions are shown as clinical guidance.
Approving a version supersedes the previous one and regenerates daily tasks.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RecoveryPlan, RecoveryPlanVersion, RecoveryTask, User
from app.services import audit
from app.services.patients import PHASES


def generate_tasks(db: Session, version: RecoveryPlanVersion, patient_id) -> int:
    content = version.content or {}
    count = 0
    for t in content.get("daily_tasks", []):
        db.add(RecoveryTask(plan_version_id=version.id, patient_id=patient_id, day_from=t["day_from"],
                            day_to=t["day_to"], category=t["category"], title=t["title"], detail=t.get("detail", ""),
                            caregiver_visible=t.get("caregiver_visible", True)))
        count += 1
    db.flush()
    return count


class RecoveryPlanAgent:
    def create_version(self, db: Session, plan: RecoveryPlan, content: dict, author: User,
                       change_summary: str) -> RecoveryPlanVersion:
        last = db.scalars(select(RecoveryPlanVersion).where(RecoveryPlanVersion.plan_id == plan.id)
                          .order_by(RecoveryPlanVersion.version.desc())).first()
        v = RecoveryPlanVersion(plan_id=plan.id, version=(last.version + 1) if last else 1, status="PENDING_APPROVAL",
                                content=content, created_by_id=author.id, change_summary=change_summary)
        db.add(v)
        db.flush()
        audit.record(db, "PLAN_VERSION_CREATED", actor=author, patient_id=plan.patient_id,
                     resource_type="recovery_plan_version", resource_id=v.id,
                     details={"version": v.version, "change_summary": change_summary})
        return v

    def approve(self, db: Session, version: RecoveryPlanVersion, approver: User) -> RecoveryPlanVersion:
        if version.status not in ("PENDING_APPROVAL", "DRAFT"):
            raise HTTPException(409, f"Version is {version.status}")
        if version.created_by_id == approver.id:
            raise HTTPException(409, "Plans must be approved by a different clinician than the author")
        plan = db.get(RecoveryPlan, version.plan_id)
        for old in db.scalars(select(RecoveryPlanVersion).where(RecoveryPlanVersion.plan_id == plan.id,
                                                                RecoveryPlanVersion.status == "APPROVED")):
            old.status = "SUPERSEDED"
        version.status = "APPROVED"
        version.approved_by_id = approver.id
        version.approved_at = datetime.now(timezone.utc)
        plan.current_version_id = version.id
        n = generate_tasks(db, version, plan.patient_id)
        audit.record(db, "PLAN_VERSION_APPROVED", actor=approver, patient_id=plan.patient_id,
                     resource_type="recovery_plan_version", resource_id=version.id,
                     details={"version": version.version, "tasks_generated": n})
        return version

    @staticmethod
    def phases() -> list[dict]:
        return [{"key": k, "label": label, "start_day": s, "end_day": e, "description": d}
                for k, s, e, label, d in PHASES]
