"""Integration use cases, standards and pipeline, served to the admin "Integrations" page.

Describes how post-surgical data reaches a recovery program in US healthcare without manual
entry, and which of those feeds this POC implements (`status: LIVE`) versus plans (`PLANNED`).
"""
from __future__ import annotations

USE_CASES: list[dict] = [
    {
        "id": "discharge", "title": "Hospital discharge (ADT)", "status": "LIVE", "channel": "HL7V2",
        "manual_today": "A coordinator reads the discharge list and types the discharge date into the program.",
        "automated": "The hospital's interface engine forwards the ADT^A03 discharge event the moment the patient "
                     "leaves. The program updates the episode's discharge date, and the recovery day and plan "
                     "phase follow from it.",
        "standards": ["HL7 v2 ADT^A03", "FHIR Encounter"],
        "source_systems": ["EHR ADT feed via interface engine (e.g. Rhapsody, Mirth/NextGen Connect, Cloverleaf)",
                           "Event-notification services (CMS Conditions of Participation require hospitals to send "
                           "ADT notifications)"],
        "data": ["Patient MRN", "Admit and discharge time", "Discharge disposition"],
        "endpoint": "POST /api/integrations/hl7v2  or  POST /api/integrations/fhir",
    },
    {
        "id": "medications", "title": "Discharge medications", "status": "LIVE", "channel": "FHIR",
        "manual_today": "A nurse copies the discharge medication list from the EHR into the app.",
        "automated": "MedicationRequest resources from the EHR's FHIR API create or update the patient's medication "
                     "list. New medications have no missed-dose guidance until the doctor approves it, so a "
                     "medication-reconciliation task is created for the doctor automatically.",
        "standards": ["FHIR R4 MedicationRequest (US Core)", "RxNorm", "HL7 v2 RDE^O11 (planned)"],
        "source_systems": ["EHR FHIR R4 API (ONC-certified EHRs expose US Core)", "e-prescribing records"],
        "data": ["Drug name (RxNorm)", "Dose and frequency text", "PRN flag", "Prescriber", "Reason"],
        "endpoint": "POST /api/integrations/fhir",
    },
    {
        "id": "appointments", "title": "Follow-up appointments", "status": "LIVE", "channel": "HL7V2",
        "manual_today": "Staff re-enter post-op visits and PT sessions so reminders can be sent.",
        "automated": "Scheduling events (SIU^S12) or FHIR Appointment resources add the visit to the patient's "
                     "appointments, and the existing reminder and transport-check jobs pick it up.",
        "standards": ["HL7 v2 SIU^S12", "FHIR R4 Appointment"],
        "source_systems": ["EHR / practice-management scheduling", "Outpatient PT scheduling systems"],
        "data": ["Start time and duration", "Visit type", "Provider", "Location"],
        "endpoint": "POST /api/integrations/hl7v2  or  POST /api/integrations/fhir",
    },
    {
        "id": "rpm", "title": "Remote patient monitoring devices", "status": "LIVE", "channel": "DEVICE",
        "manual_today": "Patients read their thermometer and type the number into the daily check-in.",
        "automated": "Cellular or Bluetooth devices (thermometer, pulse oximeter, BP cuff, scale) upload to the "
                     "device vendor's cloud, which posts readings here. Each reading is unit-converted, "
                     "range-checked and run through the same surgeon-approved warning protocols as a check-in, "
                     "so a fever raises the same nurse alert without waiting for the next check-in.",
        "standards": ["Vendor REST webhooks", "LOINC + UCUM", "IEEE 11073 / Bluetooth health profiles (device side)",
                      "CPT 99453 / 99454 / 99457 (RPM billing)"],
        "source_systems": ["RPM device vendor clouds", "RPM aggregation platforms"],
        "data": ["Temperature", "Heart rate", "SpO₂", "Blood pressure", "Weight"],
        "endpoint": "POST /api/integrations/devices",
    },
    {
        "id": "wearables", "title": "Wearables and phone health data", "status": "LIVE", "channel": "DEVICE",
        "manual_today": "Patients estimate walking minutes in the check-in.",
        "automated": "With the patient's consent, the patient app syncs steps and heart rate from Apple HealthKit or "
                     "Google Health Connect and posts them to the same device feed.",
        "standards": ["Apple HealthKit", "Google Health Connect", "LOINC 41950-7 (steps)"],
        "source_systems": ["Patient mobile app"],
        "data": ["Daily steps", "Resting heart rate"],
        "endpoint": "POST /api/integrations/devices",
    },
    {
        "id": "vitals", "title": "Clinic and home-health vitals", "status": "LIVE", "channel": "HL7V2",
        "manual_today": "Home-health nurses phone in vitals, or they are only visible in the EHR.",
        "automated": "Observation results (ORU^R01 or FHIR Observation) recorded by home-health or clinic staff in "
                     "the EHR flow in and are evaluated against the approved protocols.",
        "standards": ["HL7 v2 ORU^R01", "FHIR R4 Observation (US Core Vital Signs)", "LOINC"],
        "source_systems": ["EHR results interface", "Home-health agency systems"],
        "data": ["Temperature", "Heart rate", "SpO₂", "Blood pressure"],
        "endpoint": "POST /api/integrations/hl7v2  or  POST /api/integrations/fhir",
    },
    {
        "id": "surgery", "title": "Surgical case details", "status": "PARTIAL", "channel": "FHIR",
        "manual_today": "The surgery type and date are typed in at enrollment.",
        "automated": "Procedure resources are read and checked against the enrolled episode; a mismatch is flagged "
                     "in the message log. Creating enrollments automatically from OR schedules is planned and would "
                     "go through an enrollment worklist, so no patient is enrolled without human review.",
        "standards": ["FHIR R4 Procedure", "CPT / SNOMED CT", "HL7 v2 SIU (OR scheduling)"],
        "source_systems": ["EHR surgical module", "OR scheduling"],
        "data": ["Procedure", "Surgery date", "Surgeon"],
        "endpoint": "POST /api/integrations/fhir",
    },
    {
        "id": "pharmacy_fills", "title": "Pharmacy fill status", "status": "LIVE", "channel": "PHARMACY",
        "manual_today": "Nobody knows whether the discharge prescriptions were picked up.",
        "automated": "The pharmacy network sends an NCPDP SCRIPT RxFill each time a prescription is dispensed or "
                     "not picked up. Fills are matched to the patient's medication list; a prescription that was "
                     "not dispensed creates an AMBER nurse outreach task (any change to the prescription itself "
                     "is the doctor's decision).",
        "standards": ["NCPDP SCRIPT 2017071 RxFill", "Status 010 / Error 900 replies"],
        "source_systems": ["E-prescribing network (e.g. Surescripts)", "Retail / specialty pharmacy systems"],
        "data": ["Fill status", "Drug", "Quantity and days supply", "Fill date", "Pharmacy"],
        "endpoint": "POST /api/integrations/ncpdp",
    },
    {
        "id": "pros", "title": "Patient-reported outcomes (PROMs)", "status": "LIVE", "channel": "OUTBOUND",
        "manual_today": "Paper or portal surveys are transcribed for quality reporting.",
        "automated": "Hip and knee patients get the HOOS JR / KOOS JR survey in the app at 2 weeks and 30 days. "
                     "Each completed survey is scored and sent to the EHR as a FHIR QuestionnaireResponse for CMS "
                     "joint-replacement quality reporting.",
        "standards": ["FHIR QuestionnaireResponse", "HOOS JR (LOINC 72095-5)", "KOOS JR (LOINC 72093-0)"],
        "source_systems": ["This app → EHR / registry"],
        "data": ["Item answers (0–4)", "Raw score", "Time point"],
        "endpoint": "Patient app › Surveys  →  outbound queue",
    },
    {
        "id": "outbound", "title": "Alerts back to the EHR", "status": "LIVE", "channel": "OUTBOUND",
        "manual_today": "Nurses document app alerts again in the EHR.",
        "automated": "Every RED and AMBER alert is queued as a FHIR Communication for the patient's chart. A "
                     "delivery job posts queued resources to the EHR with retries (exponential backoff, failed "
                     "after 5 attempts and retryable from the Outbound tab). Without an EHR endpoint configured, "
                     "delivery is simulated.",
        "standards": ["FHIR R4 Communication", "FHIR QuestionnaireResponse", "OUTBOUND_FHIR_URL + bearer token"],
        "source_systems": ["This app → EHR FHIR API"],
        "data": ["Alert, severity, response time", "Survey results"],
        "endpoint": "Scheduler → POST {OUTBOUND_FHIR_URL}/{resourceType}",
    },
    {
        "id": "transport", "title": "Rides to follow-up visits", "status": "LIVE", "channel": "APP",
        "manual_today": "Missed visits are discovered after the fact; staff phone patients to ask about rides.",
        "automated": "The day before each appointment the patient is asked (in-app and SMS) how they'll get there. "
                     "They can confirm their own ride, request a hospital pickup with their address and mobility "
                     "needs, or ask for help. A coordinator books the shuttle, medical transport van or rideshare; "
                     "the patient gets the pickup time and confirmation code and a reminder the day before. No answer "
                     "12 hours before the visit creates a coordinator task.",
        "standards": ["In-app request + coordinator worklist", "NEMT / rideshare vendor booking"],
        "source_systems": ["Patient app", "Hospital shuttle, NEMT broker or rideshare-for-health vendor"],
        "data": ["Pickup address and time", "Mobility needs", "Vehicle, driver, confirmation"],
        "endpoint": "POST /api/patients/{id}/appointments/{id}/transport-request",
    },
]

STANDARDS: list[dict] = [
    {"name": "HL7 v2", "what": "Pipe-delimited event messages (ADT, ORU, SIU, RDE). Still the backbone of "
                               "in-hospital feeds, delivered over MLLP/TLS or HTTPS through an interface engine."},
    {"name": "FHIR R4 / US Core", "what": "REST resources (Patient, Encounter, MedicationRequest, Appointment, "
                                          "Observation). ONC Cures Act rules require certified EHRs to offer "
                                          "standardized FHIR APIs covering USCDI data."},
    {"name": "SMART Backend Services", "what": "OAuth 2.0 client-credentials with a signed JWT, used for "
                                               "system-to-system FHIR access. Planned replacement for the POC's "
                                               "API keys."},
    {"name": "C-CDA", "what": "XML discharge summaries and continuity-of-care documents exchanged through HIEs "
                              "and national networks (Carequality, CommonWell, TEFCA). Planned."},
    {"name": "NCPDP SCRIPT", "what": "E-prescribing standard. RxFill fill notifications are accepted at "
                                     "/api/integrations/ncpdp (XML, DTDs refused)."},
    {"name": "LOINC · UCUM · RxNorm · SNOMED CT", "what": "Code systems for observations, units, drugs and "
                                                          "clinical concepts. Readings are accepted only for "
                                                          "known LOINC codes and converted to canonical units."},
]

PIPELINE: dict = {
    "id": "inbound", "title": "Inbound message pipeline",
    "summary": "Every feed (FHIR, HL7 v2, device) runs through the same steps. Clinical thresholds come only from "
               "approved warning protocols; nothing is diagnosed or changed automatically.",
    "steps": [
        {"label": "Message arrives", "kind": "start",
         "detail": "POST /api/integrations/{fhir | hl7v2 | devices | ncpdp}"},
        {"label": "Authenticate the source", "kind": "decision", "detail": "X-Integration-Key, hashed; source active "
                                                                            "and allowed for this channel",
         "branches": [{"when": "Unknown, inactive or wrong channel", "outcome": "401 / 403, nothing stored",
                       "kind": "end"},
                      {"when": "Valid", "outcome": "Continue below", "kind": "step"}]},
        {"label": "Idempotency check", "kind": "decision", "detail": "Message id (MSH-10, Bundle id, message_id)",
         "branches": [{"when": "Already processed", "outcome": "Return the original result (DUPLICATE)",
                       "kind": "end"},
                      {"when": "New", "outcome": "Continue below", "kind": "step"}]},
        {"label": "Parse and normalize", "kind": "decision",
         "detail": "LOINC → reading type, units → canonical (°C → °F, kg → lb), plausibility ranges",
         "branches": [{"when": "Malformed / no MRN", "outcome": "REJECTED (HL7 ACK AR)", "kind": "end"},
                      {"when": "Some items invalid", "outcome": "Use the rest, list the errors (PARTIAL)",
                       "kind": "step"},
                      {"when": "Valid", "outcome": "Continue below", "kind": "step"}]},
        {"label": "Match patient by MRN", "kind": "decision", "detail": "Enrolled patients only",
         "branches": [{"when": "No enrolled patient", "outcome": "REJECTED; never auto-enrolled", "kind": "end"},
                      {"when": "Matched", "outcome": "Continue below", "kind": "step"}]},
        {"label": "Apply to the record", "kind": "step", "agent": "integration_intake",
         "detail": "Discharge date · medications (+ doctor reconciliation task) · appointments · readings · "
                   "pharmacy fills"},
        {"label": "Evaluate approved warning protocols", "kind": "decision", "detail": "Same rules engine as "
                                                                                       "check-ins, on device facts",
         "branches": [{"when": "RED / AMBER match", "outcome": "Care-team alert with SLA (+ SMS for RED)",
                       "kind": "end", "agent": "alerting"},
                      {"when": "No match", "outcome": "Readings stored (GREEN)", "kind": "end"}]},
        {"label": "Log, audit and acknowledge", "kind": "end",
         "detail": "Encrypted payload in the message log, audit event, HL7 ACK AA / AE or JSON result"},
    ],
}

OUTBOUND_PIPELINE: dict = {
    "id": "outbound", "title": "Outbound to the EHR",
    "summary": "Clinical findings and survey results are written back to the chart, so the EHR stays the source of "
               "truth and nurses don't document twice.",
    "steps": [
        {"label": "RED / AMBER alert created, or survey completed", "kind": "start", "agent": "alerting"},
        {"label": "Build the FHIR resource", "kind": "step",
         "detail": "Communication (alert) or QuestionnaireResponse (survey), patient identified by MRN"},
        {"label": "Queue", "kind": "step", "detail": "outbound_messages, payload encrypted, one per alert/survey"},
        {"label": "Deliver (scheduler, every 5 min)", "kind": "decision",
         "detail": "POST {OUTBOUND_FHIR_URL}/{resourceType}",
         "branches": [{"when": "2xx", "outcome": "SENT", "kind": "end"},
                      {"when": "Error / timeout", "outcome": "Retry with backoff; FAILED after 5 attempts",
                       "kind": "step"},
                      {"when": "No EHR endpoint configured", "outcome": "SENT (simulated)", "kind": "end"}]},
    ],
}
