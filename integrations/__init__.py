"""Inbound integrations: EHR (FHIR R4, HL7 v2) and remote-monitoring device feeds.

Parsers here are pure functions: raw message -> `InboundRecord`. They never touch
the database; `app.services.integrations` applies records to patient data.
"""
