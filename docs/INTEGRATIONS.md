# Integrations: automated post-surgical inputs

Most of what a recovery program needs after surgery already exists electronically in US healthcare. Instead of
staff or patients re-typing it, these feeds post it to the app:

| Input | Typical sender | Standard | Status |
|---|---|---|---|
| Hospital discharge | EHR ADT feed via interface engine | HL7 v2 `ADT^A03`, FHIR `Encounter` | Live |
| Discharge medications | EHR FHIR R4 API | FHIR `MedicationRequest` (US Core), RxNorm | Live |
| Follow-up appointments | EHR / PT scheduling | HL7 v2 `SIU^S12`, FHIR `Appointment` | Live |
| Clinic / home-health vitals | EHR results interface | HL7 v2 `ORU^R01`, FHIR `Observation`, LOINC | Live |
| Remote monitoring devices | RPM vendor cloud | Vendor webhook → device JSON, LOINC + UCUM | Live |
| Wearables | Patient app (HealthKit / Health Connect) | Device JSON | Live |
| Surgical case details | EHR surgical module | FHIR `Procedure` | Partial: checked against the episode, no auto-enrollment |
| Pharmacy fill status | E-prescribing network | NCPDP SCRIPT `RxFill` | Live |
| Patient-reported outcomes | This app → EHR | HOOS JR / KOOS JR in the app → FHIR `QuestionnaireResponse` | Live |
| Alerts back to the EHR | This app → EHR | FHIR `Communication` (RED / AMBER alerts) | Live (simulated until `OUTBOUND_FHIR_URL` is set) |
| Rides to follow-up visits | Patient app → coordinator | In-app request, coordinator booking (shuttle / NEMT / rideshare) | Live |

The admin console (**Admin › Integrations**) explains each use case, shows the pipeline, manages sources and keys,
lists every received message, and has a simulator that sends sample messages through the real pipeline.

## Pipeline

```
POST /api/integrations/{fhir | hl7v2 | devices | ncpdp}
 → authenticate source (X-Integration-Key, stored as SHA-256; active; channel matches)   401 / 403
 → parse (integrations/fhir.py · hl7v2.py · devices.py)                                    REJECTED / ACK AR
 → idempotency: (source, message id) — MSH-10, Bundle.id/identifier, message_id, else payload hash
 → match patient by MRN (enrolled, ACTIVE only; never creates enrollments)                 REJECTED
 → apply (backend/app/services/integrations.py)
     discharge date  (held for review if > 30 days after surgery and a date is already recorded)
     medications     create / update by name; new ones get NO missed-dose guidance → INT-MED-RECONCILE task for the doctor
     appointments    create / update by (time, type)
     readings        LOINC → kind, units → canonical (°C→°F, kg→lb), plausibility ranges → device_readings
     pharmacy fills  matched to the medication list by drug name; NOT_DISPENSED → INT-RX-NOT-FILLED nurse outreach
 → readings from the last 24 h: approved warning protocols (same rules engine as check-ins)
     match → one alert (source INTEGRATION) with the readings as evidence; patient notified with the protocol's message
 → inbound_messages row (raw payload encrypted), audit INTEGRATION_MESSAGE_RECEIVED, metrics
 → response: JSON receipt (no PHI) · HL7 ACK (AA processed, AE partial, AR rejected) · NCPDP Status 010 / Error 900
```

Statuses: `PROCESSED`, `PARTIAL` (some items invalid; the rest applied, errors listed), `REJECTED`. A re-delivered
message returns the original receipt with `"duplicate": true`.

Device facts available to warning protocols: `temperature_f`, `pain_score`, `heart_rate`, `spo2`, `bp_systolic`,
`bp_diastolic`, `weight_lb`, `steps_24h`. Today's approved protocols use `temperature_f` (fever, low-grade
temperature); clinicians can add protocols on the other facts through the normal approval workflow.

## Sources and keys

Seeded sources: `ehr-fhir`, `ehr-hl7`, `rpm-devices`, `patient-wearables`, `pharmacy-network`. Their development key is
`<INTEGRATION_DEMO_KEY>-<slug>` (default `dev-integration-key-rpm-devices`, …). The app refuses to start in
production with the default `INTEGRATION_DEMO_KEY`. Rotating a key in the console issues a new random key, shown
once; disabling a source rejects its messages with 403.

## Examples

```bash
# Device reading (38.6 °C → RED-FEVER alert)
curl -X POST http://localhost:8080/api/integrations/devices \
  -H 'X-Integration-Key: dev-integration-key-rpm-devices' -H 'Content-Type: application/json' \
  -d '{"message_id":"rpm-0001","patient":{"mrn":"SYN-100200"},"device":{"type":"THERMOMETER"},
       "readings":[{"type":"TEMPERATURE","value":38.6,"unit":"Cel","measured_at":"2026-11-04T08:00:00Z"}]}'

# HL7 v2 ORU^R01 (returns an ACK)
printf 'MSH|^~\\&|EHR|HOSP|RC|POC|20261104080000||ORU^R01|MSG0001|P|2.5.1\rPID|1||SYN-100200^^^HOSP^MR\rOBX|1|NM|8310-5^Body temperature^LN||100.6|[degF]|||||F\r' \
  | curl -X POST http://localhost:8080/api/integrations/hl7v2 \
    -H 'X-Integration-Key: dev-integration-key-ehr-hl7' -H 'Content-Type: text/plain' --data-binary @-
```

```bash
# NCPDP SCRIPT RxFill: prescription not picked up → AMBER nurse outreach task
curl -X POST http://localhost:8080/api/integrations/ncpdp \
  -H 'X-Integration-Key: dev-integration-key-pharmacy-network' -H 'Content-Type: application/xml' \
  -d '<Message><Header><MessageID>RXF-0001</MessageID></Header><Body><RxFill><FillStatus><NotDispensed/></FillStatus>
      <Patient><HumanPatient><Identification><MedicalRecordIdentificationNumberEHR>SYN-100200</MedicalRecordIdentificationNumberEHR>
      </Identification></HumanPatient></Patient><MedicationDispensed><DrugDescription>Apixaban 2.5 mg tablet</DrugDescription>
      </MedicationDispensed></RxFill></Body></Message>'
```

XML with a `DOCTYPE` or `ENTITY` declaration is refused before parsing.

Sample messages for every scenario are in `integrations/samples.py`.

## Outbound to the EHR

```
RED / AMBER alert created  → FHIR Communication        ┐
HOOS JR / KOOS JR completed → FHIR QuestionnaireResponse ┘→ outbound_messages (payload encrypted, one per item)
  → scheduler (every 5 min) POST {OUTBOUND_FHIR_URL}/{resourceType}  (Bearer OUTBOUND_FHIR_TOKEN)
      2xx → SENT · error → retry after 2, 4, 8, 16 min → FAILED after 5 attempts (retry from Admin › Integrations › Outbound)
  → no OUTBOUND_FHIR_URL → SENT (simulated): built and logged, not sent
```

INFO tasks (transport, reconciliation, contact requests) stay in the program and are not written to the chart.

## Patient-reported outcomes

Hip (THA) patients get **HOOS JR** and knee (TKA) patients **KOOS JR** at two time points: 2 weeks (recovery days
14–20) and 30 days (days 26–30). Each survey can be completed once per time point. The POC stores the **raw sum**
(0 = no problems; HOOS JR 0–24, KOOS JR 0–28). The official 0–100 interval score needs the instrument's published
conversion table, which is not bundled; check item wording against the licensed instrument before production use.
CMS reporting windows (pre-op and 9–14 months post-op) are outside the 30-day program.

## Rides to appointments

- 36 h before an appointment the patient is asked (in-app + PHI-minimal SMS) how they'll get there: own ride,
  hospital pickup (address, walker / wheelchair / step help, companion, return trip) or "help me find a ride".
- A request is an `APPT-TRANSPORT` coordinator task; **Care team › Rides to visits** books it (hospital shuttle,
  medical transport van (NEMT), rideshare or volunteer driver, pickup time, vehicle, driver, confirmation code),
  which notifies the patient and resolves the task.
- Booked rides get a reminder the day before; no answer 12 h before the visit creates `APPT-TRANSPORT-UNCONFIRMED`.
- Production: book through the NEMT broker's or rideshare-for-health vendor's API instead of by phone.

## POC limitations / production plan

- **Auth:** API keys → SMART Backend Services (OAuth 2.0 client credentials + signed JWT) for FHIR, and mutual
  TLS or a VPN to the interface engine for HL7 (MLLP or HTTPS). BAA with every vendor.
- **Transport:** synchronous HTTP processing; production queues messages (e.g. SQS) and processes asynchronously
  with retries and a dead-letter queue.
- **Time zones:** HL7 timestamps without an offset are treated as UTC; production uses the facility's zone.
- **Patient matching:** exact MRN only. Production adds an enterprise MPI / identifier-system check and a review
  worklist for unmatched messages.
- **Pull:** the EHR pushes today; FHIR Subscriptions or scheduled `$export` (Bulk FHIR) pulls are not implemented.
- Not yet supported: `RDE^O11`, `ADT^A13` (cancel discharge), C-CDA documents, other NCPDP transactions
  (only `RxFill`).
