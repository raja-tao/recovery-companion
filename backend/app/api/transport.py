"""Rides to appointments: patient requests, coordinator booking."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, patient_access, require
from app.api.serializers import appointment_out, iso
from app.core.database import get_db
from app.core.security import Perm
from app.models import Appointment, Patient, TransportRequest, User
from app.schemas import TransportCancel, TransportRequestCreate, TransportSchedule
from app.services import audit
from app.services import transport as svc

router = APIRouter(tags=["Transport"])


def _appt(db: Session, patient_id, appointment_id) -> Appointment:
    appt = db.get(Appointment, appointment_id)
    if not appt or appt.patient_id != patient_id:
        raise HTTPException(404, "Appointment not found")
    return appt


@router.get("/transport/options", summary="Ride modes and mobility needs")
def options(user: User = Depends(get_current_user)):
    return {"modes": [{"key": k, "label": v} for k, v in svc.MODES.items()],
            "mobility_needs": [{"key": k, "label": v} for k, v in svc.MOBILITY.items()]}


@router.post("/patients/{patient_id}/appointments/{appointment_id}/transport-request",
             summary="Ask the hospital for a pickup, or for help finding a ride")
def request_ride(patient_id: uuid.UUID, appointment_id: uuid.UUID, body: TransportRequestCreate,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = patient_access(db, user, patient_id, self_perm=Perm.SELF_APPOINTMENTS, staff_perm=Perm.TRANSPORT_MANAGE)
    appt = _appt(db, p.id, appointment_id)
    r = svc.create_request(db, user, p, appt, kind=body.kind, pickup_address=body.pickup_address,
                           requested_pickup_at=body.requested_pickup_at, return_trip=body.return_trip,
                           mobility_needs=list(body.mobility_needs), companion=body.companion, note=body.note)
    db.commit()
    return appointment_out(appt) | {"transport": svc.request_out(r),
                                    "message": "Thanks — a care coordinator will book your ride and send you the "
                                               "pickup time."}


@router.post("/patients/{patient_id}/transport-requests/{request_id}/cancel",
             summary="Cancel a ride request (patient: 'I have my own ride now')")
def patient_cancel(patient_id: uuid.UUID, request_id: uuid.UUID, body: TransportCancel,
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = patient_access(db, user, patient_id, self_perm=Perm.SELF_APPOINTMENTS, staff_perm=Perm.TRANSPORT_MANAGE)
    r = db.get(TransportRequest, request_id)
    if not r or r.patient_id != p.id:
        raise HTTPException(404, "Request not found")
    svc.cancel(db, user, r, body.reason)
    db.commit()
    return svc.request_out(r)


# --------------------------------------------------------------------------- coordinator
@router.get("/transport-requests", summary="Ride requests to arrange (care coordinators)")
def list_requests(user: User = Depends(require(Perm.TRANSPORT_MANAGE)), db: Session = Depends(get_db),
                  status: str | None = Query(None, description="Comma-separated; default open requests")):
    statuses = status.split(",") if status else list(svc.OPEN)
    rows = db.execute(select(TransportRequest, Appointment, Patient)
                      .join(Appointment, Appointment.id == TransportRequest.appointment_id)
                      .join(Patient, Patient.id == TransportRequest.patient_id)
                      .where(TransportRequest.status.in_(statuses)).order_by(Appointment.scheduled_at)).all()
    audit.record(db, "PHI_VIEW_TRANSPORT_REQUESTS", actor=user, details={"count": len(rows)})
    db.commit()
    return [svc.request_out(r, staff=True) | {
        "patient_id": str(p.id), "patient_name": p.full_name, "patient_phone": p.phone, "mrn": p.mrn,
        "appointment": appointment_out(a)} for r, a, p in rows]


def _request(db: Session, request_id: uuid.UUID) -> TransportRequest:
    r = db.get(TransportRequest, request_id)
    if not r:
        raise HTTPException(404, "Request not found")
    return r


@router.post("/transport-requests/{request_id}/schedule", summary="Book the ride and tell the patient")
def schedule(request_id: uuid.UUID, body: TransportSchedule, user: User = Depends(require(Perm.TRANSPORT_MANAGE)),
             db: Session = Depends(get_db)):
    r = svc.schedule(db, user, _request(db, request_id), **body.model_dump())
    db.commit()
    return svc.request_out(r, staff=True)


@router.post("/transport-requests/{request_id}/cancel", summary="Cancel a ride (coordinator)")
def staff_cancel(request_id: uuid.UUID, body: TransportCancel, user: User = Depends(require(Perm.TRANSPORT_MANAGE)),
                 db: Session = Depends(get_db)):
    r = svc.cancel(db, user, _request(db, request_id), body.reason)
    db.commit()
    return svc.request_out(r, staff=True)


@router.post("/transport-requests/{request_id}/complete", summary="Mark a ride as completed")
def complete(request_id: uuid.UUID, user: User = Depends(require(Perm.TRANSPORT_MANAGE)),
             db: Session = Depends(get_db)):
    r = svc.complete(db, user, _request(db, request_id))
    db.commit()
    return svc.request_out(r, staff=True) | {"updated_at": iso(r.updated_at)}
