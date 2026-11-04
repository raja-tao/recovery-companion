"""Synthetic seed data. NO REAL PHI — every person, MRN, phone and email is fictional.

Run: `python -m app.seed` (or automatically on startup when the DB is empty).
`python -m app.seed --reset` drops and recreates everything.
"""
from __future__ import annotations

import argparse
import os
import random
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from agents.checkin_analysis import CheckinAnalysisAgent
from agents.recovery_plan import generate_tasks
from app.core.database import Base, SessionLocal, get_engine, init_schema
from app.core.security import ROLE_PERMISSIONS, Role, hash_password
from app.models import (
    Alert, Appointment, Caregiver, CaregiverPermission, CareTeamAction, Checkin, CheckinQuestion, Document,
    EducationContent, Medication, MedicationEvent, Patient, Program, RecoveryPlan, RecoveryPlanVersion, RoleModel,
    SurgicalEpisode, User, WarningProtocol,
)
from app.services import alerts as alert_svc
from app.services import audit
from app.services.scheduler import detect_missed_checkins
from rag.ingestion import checksum, index_document

DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "Recovery#2026")
KNOWLEDGE_DIR = Path(os.environ.get("KNOWLEDGE_DIR", Path(__file__).resolve().parents[2] / "knowledge"))
UTC = timezone.utc


def now() -> datetime:
    return datetime.now(UTC)


# =========================================================================== reference data
STAFF = [
    ("nurse@example.com", "Nina Patel", Role.NURSE, "RN, Care Manager"),
    ("nurse2@example.com", "Marcus Bell", Role.NURSE, "RN, Care Manager"),
    ("doctor@example.com", "Dr. Samuel Okafor", Role.SURGEON, "Orthopedic Surgeon"),
    ("doctor2@example.com", "Dr. Elena Garcia", Role.SURGEON, "General Surgeon"),
    ("admin@example.com", "Avery Admin", Role.ADMIN, "Program Administrator"),
    ("caregiver@example.com", "Casey Lee", Role.CAREGIVER, None),
    ("caregiver2@example.com", "Sam Rivera", Role.CAREGIVER, None),
]

PROCEDURES = {
    "TKA": ("Total knee arthroplasty (right)", "doctor@example.com", "ortho"),
    "THA": ("Total hip arthroplasty (left)", "doctor@example.com", "ortho"),
    "ACL": ("ACL reconstruction (right knee)", "doctor@example.com", "ortho"),
    "LAP_CHOLE": ("Laparoscopic cholecystectomy", "doctor2@example.com", "general"),
}

# (first, last, sex, procedure, post-op day, scenario, login email)
PATIENTS = [
    ("Jordan", "Lee", "F", "TKA", 5, "normal_demo", "patient@example.com"),
    ("John", "Smith", "M", "TKA", 6, "red_fever_wound", None),
    ("Mary", "Smith", "F", "THA", 9, "missed_checkins", "mary.smith@example.com"),
    ("Robert", "Chen", "M", "LAP_CHOLE", 3, "amber_pain", None),
    ("Linda", "Gomez", "F", "THA", 12, "transport", None),
    ("David", "Kim", "M", "ACL", 4, "med_question", "david.kim@example.com"),
    ("Patricia", "Brown", "F", "TKA", 8, "resolved_emergency", None),
    ("Michael", "Johnson", "M", "TKA", 15, "normal", None),
    ("Susan", "Davis", "F", "THA", 21, "normal", None),
    ("James", "Wilson", "M", "LAP_CHOLE", 10, "normal", None),
    ("Karen", "Martinez", "F", "ACL", 18, "amber_swelling", None),
    ("William", "Anderson", "M", "TKA", 25, "normal", None),
    ("Nancy", "Taylor", "F", "LAP_CHOLE", 6, "normal", None),
    ("Thomas", "Thomas", "M", "THA", 2, "normal", None),
    ("Lisa", "Moore", "F", "TKA", 11, "med_adherence", None),
    ("Daniel", "Jackson", "M", "ACL", 28, "normal", None),
    ("Betty", "White", "F", "THA", 16, "resolved_red", None),
    ("Paul", "Harris", "M", "LAP_CHOLE", 13, "normal", None),
    ("Sandra", "Clark", "F", "TKA", 7, "normal", None),
    ("Mark", "Lewis", "M", "THA", 19, "resolved_red", None),
    ("Emily", "Walker", "F", "ACL", 9, "normal", None),
    ("Steven", "Hall", "M", "TKA", 1, "pending_plan", None),
    ("Donna", "Allen", "F", "LAP_CHOLE", 4, "normal", None),
    ("Kevin", "Young", "M", "THA", 23, "normal", None),
    ("Carol", "King", "F", "TKA", 14, "normal_demo2", "patient2@example.com"),
    ("Brian", "Scott", "M", "ACL", 3, "normal", None),
]

CHECKIN_QUESTIONS = [
    # key, text, type, options, min, max, unit, required, order, help
    ("pain_score", "How is your pain right now?", "SCALE", [], 0, 10, None, True, 10,
     "0 = no pain, 10 = worst pain imaginable"),
    ("pain_trend", "Compared with yesterday, is your pain…", "CHOICE",
     [{"value": "BETTER", "label": "Better"}, {"value": "SAME", "label": "About the same"},
      {"value": "WORSE", "label": "Worse"}], None, None, None, True, 20, None),
    ("temperature", "What is your temperature? (skip if you don't have a thermometer)", "NUMBER", [], 94, 108, "°F",
     False, 30, "Take it before any fever-reducing medicine if you can"),
    ("wound_appearance", "How does your incision look today?", "CHOICE",
     [{"value": "HEALING_WELL", "label": "Clean, dry, healing"}, {"value": "MORE_RED", "label": "More red than yesterday"},
      {"value": "RED_AND_WARM", "label": "Red and warm to touch"},
      {"value": "DRAINAGE", "label": "Draining fluid or pus"}, {"value": "OPENING", "label": "Edges are opening"}],
     None, None, None, True, 40, None),
    ("swelling", "How is the swelling?", "CHOICE",
     [{"value": "NONE", "label": "No swelling"}, {"value": "BETTER", "label": "Better"},
      {"value": "SAME", "label": "About the same"}, {"value": "WORSE", "label": "Worse"}], None, None, None, True, 50, None),
    ("mobility", "How are you getting around?", "CHOICE",
     [{"value": "INDEPENDENT", "label": "On my own"}, {"value": "WITH_AID", "label": "With walker/crutches/cane"},
      {"value": "NEEDS_HELP", "label": "I need help from someone"}, {"value": "UNABLE", "label": "I can't get up"}],
     None, None, None, True, 60, None),
    ("walking_minutes", "About how many minutes did you walk in total yesterday?", "NUMBER", [], 0, 600, "min", False,
     70, None),
    ("medication_adherence", "Did you take your medicines as prescribed in the last 24 hours?", "CHOICE",
     [{"value": "ALL", "label": "Yes, all of them"}, {"value": "MISSED_SOME", "label": "I missed some"},
      {"value": "MISSED_MOST", "label": "I missed most"}, {"value": "NOT_SURE", "label": "Not sure"}],
     None, None, None, True, 80, None),
    ("new_symptoms", "Any of these new symptoms? (select all that apply)", "MULTI",
     [{"value": "NONE", "label": "None"}, {"value": "NAUSEA_VOMITING", "label": "Nausea or vomiting"},
      {"value": "CONSTIPATION", "label": "No bowel movement for 3+ days"},
      {"value": "NUMBNESS", "label": "New numbness or tingling"},
      {"value": "CALF_PAIN_SWELLING", "label": "Calf pain or swelling"},
      {"value": "SHORTNESS_OF_BREATH", "label": "Shortness of breath"}, {"value": "CHEST_PAIN", "label": "Chest pain"},
      {"value": "CONFUSION", "label": "Confusion"}, {"value": "HEAVY_BLEEDING", "label": "Heavy bleeding"}],
     None, None, None, False, 90, None),
    ("concern", "Anything else you want your care team to know?", "TEXT", [], None, None, None, False, 100,
     "Your care team reads this; it is not monitored 24/7. In an emergency call 911."),
]
PROCEDURE_QUESTIONS = [
    ("TKA", "exercises_done", "Did you do your home exercises today?", "BOOLEAN", 65),
    ("THA", "exercises_done", "Did you do your home exercises and follow your hip precautions?", "BOOLEAN", 65),
    ("ACL", "exercises_done", "Did you do your exercises and wear your brace as instructed?", "BOOLEAN", 65),
    ("LAP_CHOLE", "appetite", "How is your appetite?", "CHOICE", 65),
]

P = lambda fact, op, value: {"fact": fact, "op": op, "value": value}  # noqa: E731
EMERGENCY_PATIENT_MSG = ("Your answers include symptoms that can be an emergency. Call 911 now or go to the nearest "
                         "emergency department. Your care team has also been alerted.")
RED_PATIENT_MSG = ("Your answers match a warning sign in your surgeon's instructions. A nurse will call you within "
                   "15 minutes. If you feel worse or have chest pain or trouble breathing, call 911.")
AMBER_PATIENT_MSG = "Thanks — some answers need a closer look. Your care team will follow up with you today."

PROTOCOLS = [
    # rule_id, name, severity, category, condition, minutes, team, patient_message, description
    ("RED-EMERGENCY-SYMPTOMS", "Emergency symptoms reported", "RED", "EMERGENCY",
     P("new_symptoms", "contains_any", ["CHEST_PAIN", "SHORTNESS_OF_BREATH", "CONFUSION", "HEAVY_BLEEDING"]),
     15, "NURSE", EMERGENCY_PATIENT_MSG, "Any emergency symptom selected in the check-in."),
    ("RED-FEVER", "Fever ≥ 101.0°F", "RED", "CLINICAL", P("temperature_f", ">=", 101.0), 15, "NURSE",
     RED_PATIENT_MSG, "Temperature at or above the surgeon-approved fever threshold."),
    ("RED-PAIN-WORSENING", "Severe pain that is getting worse", "RED", "CLINICAL",
     {"all": [P("pain_score", ">=", 7), P("pain_worsening", "is_true", None)]}, 15, "NURSE", RED_PATIENT_MSG,
     "Pain ≥ 7/10 with a worsening trend."),
    ("RED-INFECTION-COMBO", "Wound redness with fever", "RED", "CLINICAL",
     {"all": [{"any": [P("wound_redness", "is_true", None), P("wound_drainage", "is_true", None)]},
              P("temperature_f", ">=", 100.4)]}, 15, "NURSE", RED_PATIENT_MSG,
     "Approved combination: wound redness/drainage plus temperature ≥ 100.4°F."),
    ("RED-CALF-PAIN", "Calf pain or swelling (possible clot)", "RED", "CLINICAL",
     P("new_symptoms", "contains", "CALF_PAIN_SWELLING"), 15, "NURSE", RED_PATIENT_MSG,
     "New calf pain or swelling."),
    ("AMBER-PAIN-INCREASING", "Pain increasing", "AMBER", "CLINICAL",
     {"all": [P("pain_worsening", "is_true", None), P("pain_score", ">=", 4), P("pain_score", "<", 7)]}, 240, "NURSE",
     AMBER_PATIENT_MSG, "Moderate pain with a worsening trend."),
    ("AMBER-LOW-GRADE-TEMP", "Low-grade temperature", "AMBER", "CLINICAL",
     {"all": [P("temperature_f", ">=", 100.4), P("temperature_f", "<", 101.0)]}, 240, "NURSE", AMBER_PATIENT_MSG,
     "Temperature 100.4–100.9°F."),
    ("AMBER-WOUND-CHANGE", "Incision change", "AMBER", "CLINICAL",
     P("wound_appearance", "in", ["MORE_RED", "RED_AND_WARM", "DRAINAGE", "OPENING"]), 240, "NURSE", AMBER_PATIENT_MSG,
     "Any reported change in the incision."),
    ("AMBER-SWELLING-WORSE", "Swelling getting worse", "AMBER", "CLINICAL", P("swelling", "==", "WORSE"), 240, "NURSE",
     AMBER_PATIENT_MSG, "Patient reports worsening swelling."),
    ("AMBER-MOBILITY", "Unable to get up", "AMBER", "CLINICAL", P("mobility", "==", "UNABLE"), 240, "NURSE",
     AMBER_PATIENT_MSG, "Patient reports being unable to get up."),
    ("AMBER-MED-ADHERENCE", "Medication adherence problem", "AMBER", "MEDICATION_ADHERENCE",
     {"any": [P("medication_adherence", "in", ["MISSED_SOME", "MISSED_MOST"]), P("missed_doses_48h", ">=", 2)]}, 1440,
     "NURSE", AMBER_PATIENT_MSG, "Missed doses reported in check-in or ≥ 2 missed doses recorded in 48 h."),
    ("AMBER-GI-SYMPTOMS", "Nausea/vomiting or constipation", "AMBER", "CLINICAL",
     P("new_symptoms", "contains_any", ["NAUSEA_VOMITING", "CONSTIPATION", "NUMBNESS"]), 1440, "NURSE",
     AMBER_PATIENT_MSG, "New GI or neurologic symptoms."),
    ("AMBER-MISSED-CHECKINS", "Missed check-ins", "AMBER", "MISSED_CHECKIN",
     P("consecutive_missed_checkins", ">=", 2), 1440, "NURSE", "",
     "Two or more consecutive missed daily check-ins (evaluated by the scheduler)."),
]


def plan_content(proc: str) -> dict:
    ortho = proc in ("TKA", "THA", "ACL")
    walking = {
        "STABILIZE": "Walk 5–10 minutes, 4–6 times a day with your walker or crutches." if ortho else
        "Walk 5–10 minutes every 2 hours while awake.",
        "MONITOR": "Walk 10–15 minutes, 4–5 times a day.",
        "PROGRESS": "Walk 15–20 minutes, 3–4 times a day; practice stairs with a handrail." if ortho else
        "Walk 20–30 minutes, 2–3 times a day.",
        "TRANSITION": "Walk 20–30 minutes, 2–3 times a day; work toward your normal routine.",
    }
    tasks = [
        dict(day_from=0, day_to=30, category="CHECKIN", title="Complete your daily check-in",
             detail="Takes about 2 minutes. Best done in the morning."),
        dict(day_from=0, day_to=3, category="WALKING", title="Short walks 4–6 times today", detail=walking["STABILIZE"]),
        dict(day_from=4, day_to=7, category="WALKING", title="Walk 10–15 minutes, 4–5 times", detail=walking["MONITOR"]),
        dict(day_from=8, day_to=14, category="WALKING", title="Walk 15–20 minutes, 3–4 times", detail=walking["PROGRESS"]),
        dict(day_from=15, day_to=30, category="WALKING", title="Walk 20–30 minutes, 2–3 times",
             detail=walking["TRANSITION"]),
        dict(day_from=0, day_to=14, category="WOUND", title="Check your incision",
             detail="Look for increasing redness, drainage or opening. Report changes in your check-in."),
        dict(day_from=0, day_to=30, category="HYDRATION", title="Drink 6–8 glasses of fluids",
             detail="Water and non-alcoholic drinks help prevent constipation and dizziness.", caregiver_visible=True),
    ]
    if ortho:
        tasks += [
            dict(day_from=0, day_to=30, category="PT", title="Home exercises (2–3 times)",
                 detail="Ankle pumps, quad sets, heel slides, straight-leg raises — as your therapist showed you."),
            dict(day_from=0, day_to=14, category="ACTIVITY", title="Elevate and ice 3–4 times",
                 detail="20 minutes at a time, ice wrapped in a towel; ankle above heart level."),
            dict(day_from=0, day_to=14, category="ACTIVITY", title="Wear compression stockings during the day",
                 detail="Helps prevent blood clots."),
        ]
    else:
        tasks += [dict(day_from=0, day_to=14, category="ACTIVITY", title="No lifting over 10 lb",
                       detail="Avoid lifting laundry baskets, children or groceries.")]
    doc = {"TKA": "tka-discharge-instructions", "THA": "tha-discharge-instructions",
           "ACL": "acl-discharge-instructions", "LAP_CHOLE": "lap-chole-discharge-instructions"}[proc]
    return {
        "procedure_type": proc,
        "source_documents": [doc, "general-recovery-faq", "medication-instructions"],
        "surgeon_instructions": {
            "TKA": ["Weight bearing as tolerated with walker", "Keep dressing on until 2-week visit",
                    "No driving for at least 4 weeks", "Sleep with leg straight; no pillow under the knee"],
            "THA": ["Follow hip precautions for 6 weeks", "Weight bearing as tolerated with walker",
                    "No driving for 4–6 weeks", "Pillow between legs when sleeping"],
            "ACL": ["Brace locked straight when walking and sleeping", "Crutches; weight as instructed",
                    "Cold therapy every 2 hours while awake in week 1"],
            "LAP_CHOLE": ["Low-fat meals for a few days", "No lifting over 10 lb for 2 weeks",
                          "Shower after 24 hours; no soaking for 2 weeks"],
        }[proc],
        "medication_schedule": "See your Medications tab. Doses are set by your prescriber and cannot be changed in the app.",
        "activity_goals": {
            "STABILIZE": "Rest, short walks, protect the incision.",
            "MONITOR": "Build a daily routine; watch for warning signs.",
            "PROGRESS": "Increase walking and exercises as tolerated.",
            "TRANSITION": "Return toward normal activities as your surgeon allows.",
        },
        "walking_goals": walking,
        "wound_care": ["Keep the dressing clean and dry", "No creams or powders on the incision",
                       "Check daily for redness, drainage or opening"],
        "hydration": "6–8 glasses of non-alcoholic fluids daily unless told otherwise.",
        "pt_exercises": ["Ankle pumps", "Quadriceps sets", "Heel slides", "Straight-leg raises"] if ortho else
        ["Deep breathing 10 times every hour while awake", "Walking"],
        "sleeping_position": {
            "TKA": "On your back with the leg straight; pillow under calf/heel, never under the knee.",
            "THA": "On your back with a pillow between your legs for 6 weeks.",
            "ACL": "On your back with the brace locked straight and heel propped.",
            "LAP_CHOLE": "Any comfortable position.",
        }[proc],
        "appointment_schedule": ["Physical therapy in week 1" if ortho else "Phone check-in day 2",
                                 "Surgeon follow-up at about 2 weeks"],
        "checkin_schedule": "Daily, ideally before 10:00. Reminder sent each morning.",
        "warning_signs": {
            "call_911": ["Chest pain", "Trouble breathing", "Fainting", "Sudden confusion", "Heavy bleeding"],
            "same_day": ["Temperature 101°F or higher", "Increasing redness, warmth or drainage at the incision",
                         "Pain that keeps getting worse", "New calf pain or swelling"],
            "protocol_ids": [p[0] for p in PROTOCOLS],
        },
        "daily_tasks": tasks,
    }


def medications_for(proc: str, surgeon: str) -> list[dict]:
    if proc == "LAP_CHOLE":
        return [
            dict(name="Acetaminophen", dose_text="500 mg, 2 tablets", indication="pain", frequency="Every 6 hours",
                 schedule_times=["06:00", "12:00", "18:00"], instructions="Take with water.",
                 missed_dose_guidance="If you miss a dose, take it when you remember unless it is almost time for "
                                      "your next dose. Do not take two doses at the same time."),
            dict(name="Oxycodone", dose_text="5 mg, 1 tablet", indication="severe pain", frequency="Every 6 hours as needed",
                 schedule_times=[], as_needed=True, instructions="Only for severe pain. Causes drowsiness; do not drive.",
                 missed_dose_guidance=None),
            dict(name="Ondansetron", dose_text="4 mg", indication="nausea", frequency="Every 8 hours as needed",
                 schedule_times=[], as_needed=True, instructions="Let it dissolve on your tongue.",
                 missed_dose_guidance=None),
            dict(name="Docusate", dose_text="100 mg", indication="constipation (stool softener)",
                 frequency="Twice daily", schedule_times=["08:00", "20:00"], instructions="Drink plenty of water.",
                 missed_dose_guidance="If you miss a dose, skip it and take the next dose at the usual time."),
        ]
    return [
        dict(name="Acetaminophen", dose_text="500 mg, 2 tablets", indication="pain", frequency="Every 8 hours",
             schedule_times=["06:00", "14:00", "22:00"], instructions="Take with water. Part of your pain plan.",
             missed_dose_guidance="If you miss a dose, take it when you remember unless it is almost time for your "
                                  "next dose. Do not take two doses at the same time."),
        dict(name="Oxycodone", dose_text="5 mg, 1 tablet", indication="severe pain", frequency="Every 4–6 hours as needed",
             schedule_times=[], as_needed=True,
             instructions="Only for severe pain not controlled by acetaminophen. Causes drowsiness; do not drive.",
             missed_dose_guidance=None),
        dict(name="Apixaban", dose_text="2.5 mg", indication="blood clot prevention (blood thinner)",
             frequency="Twice daily for 14 days", schedule_times=["08:00", "20:00"],
             instructions="Blood thinner to prevent blood clots. Take at the same times each day.",
             missed_dose_guidance="If you miss a dose, take it as soon as you remember on the same day, then go back "
                                  "to your normal schedule. Do not take two doses at the same time to make up for a "
                                  "missed dose.", days=14),
        dict(name="Docusate", dose_text="100 mg", indication="constipation (stool softener)", frequency="Twice daily",
             schedule_times=["08:00", "20:00"], instructions="Stool softener. Drink plenty of water.",
             missed_dose_guidance="If you miss a dose, skip it and take the next dose at the usual time."),
    ]


EDUCATION = [
    ("Caring for your incision", "Keep it clean and dry and check it every day.", "ALL", "STABILIZE", None,
     "Keep your dressing clean and dry. Do not put creams, lotions or powders on your incision. Check it every day "
     "for increasing redness, warmth, drainage or opening and report any change in your daily check-in."),
    ("Managing swelling with ice and elevation", "Ice 20 minutes at a time, ankle above your heart.", "TKA", "STABILIZE",
     "tka-discharge-instructions",
     "Elevate your leg with your ankle above your heart for 20 minutes several times a day. Apply ice wrapped in a "
     "towel for 20 minutes, 3–4 times a day. Never place a pillow directly under your knee."),
    ("Hip precautions", "Protect your new hip for the first 6 weeks.", "THA", "ALL", "tha-discharge-instructions",
     "Do not bend your hip past 90 degrees, cross your legs, or turn your operated leg inward. Use your reacher and "
     "sock aid. Sit in firm chairs with arms."),
    ("Preventing blood clots", "Move, pump your ankles, take your blood thinner.", "ALL", "MONITOR",
     "medication-instructions",
     "Do ankle pumps every hour while awake, walk regularly, wear compression stockings during the day, and take your "
     "blood thinner exactly as prescribed. Calf pain or swelling must be reported right away."),
    ("Constipation after surgery", "Fluids, fiber, walking and your stool softener.", "ALL", "STABILIZE",
     "general-recovery-faq",
     "Pain medicine and less activity often cause constipation. Drink plenty of fluids, eat fruits and vegetables, "
     "walk regularly and take your stool softener. Tell your care team if you have not had a bowel movement in 3 days."),
    ("Your walking plan", "Build up a little every day.", "ALL", "PROGRESS", None,
     "Short, frequent walks are better than one long walk. Increase your time a little each day. Use your walking aid "
     "until your therapist says you can stop."),
    ("Eating after gallbladder surgery", "Light, low-fat meals at first.", "LAP_CHOLE", "STABILIZE",
     "lap-chole-discharge-instructions",
     "Start with light, low-fat meals. Greasy or fried foods may cause bloating or diarrhea. Add your usual foods back "
     "slowly."),
    ("When to get help", "Know the difference between 911 and calling your care team.", "ALL", "ALL", None,
     "Call 911 for chest pain, trouble breathing, fainting, heavy bleeding or sudden confusion. Contact your care team "
     "the same day for a temperature of 101°F or higher, increasing redness or drainage at the incision, or pain that "
     "keeps getting worse."),
    ("Getting ready to finish the program", "What changes after day 30.", "ALL", "TRANSITION", None,
     "As you reach the end of the 30-day program, keep doing your exercises, attend your follow-up visits and ask "
     "your surgeon about returning to work, driving and other activities."),
]


# =========================================================================== helpers
def parse_frontmatter(raw: str) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
    if not m:
        return {}, raw
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, m.group(2)


def normal_answers(rng: random.Random, day: int, proc: str) -> dict:
    pain = max(1, min(6, round(6 - day * 0.25) + rng.choice([0, 0, -1])))
    a = {"pain_score": pain, "pain_trend": rng.choice(["BETTER", "BETTER", "SAME"]),
         "temperature": round(rng.uniform(97.6, 99.4), 1), "wound_appearance": "HEALING_WELL",
         "swelling": rng.choice(["BETTER", "SAME", "NONE"]) if day > 2 else "SAME",
         "mobility": "WITH_AID" if proc != "LAP_CHOLE" and day < 20 else "INDEPENDENT",
         "walking_minutes": min(120, 10 + day * 4 + rng.randint(0, 10)), "medication_adherence": "ALL",
         "new_symptoms": ["NONE"]}
    if proc == "LAP_CHOLE":
        a["appetite"] = rng.choice(["GOOD", "FAIR"])
    else:
        a["exercises_done"] = True
    return a


# =========================================================================== seed
def seed(db: Session) -> dict:
    rng = random.Random(20260101)
    today = date.today()
    pw = hash_password(DEMO_PASSWORD)

    roles = {}
    for r in Role:
        rm = RoleModel(name=r.value, description=r.value.title(), permissions=sorted(p.value for p in ROLE_PERMISSIONS[r]))
        db.add(rm)
        roles[r] = rm
    db.flush()

    users: dict[str, User] = {}
    for email, name, role, title in STAFF:
        u = User(email=email, full_name=name, role_id=roles[role].id, title=title, password_hash=pw,
                 phone=f"+1-555-01{len(users):02d}")
        db.add(u)
        users[email] = u
    db.flush()

    programs = {
        "ortho": Program(name="Orthopedic Joint Recovery — 30 Day", procedure_types=["TKA", "THA", "ACL"],
                         description="Post-discharge recovery program for joint and ligament surgery.",
                         targets={"checkin_completion": 0.7, "medication_adherence": 0.9, "followup_attendance": 0.9,
                                  "red_alert_contact_minutes": 15}),
        "general": Program(name="General Surgery Recovery — 30 Day", procedure_types=["LAP_CHOLE"],
                           description="Post-discharge recovery program for general surgery.",
                           targets={"checkin_completion": 0.7, "medication_adherence": 0.9, "followup_attendance": 0.9,
                                    "red_alert_contact_minutes": 15}),
    }
    db.add_all(programs.values())
    db.flush()

    # ----- check-in questions
    for key, txt, typ, opts, mn, mx, unit, req, order, help_ in CHECKIN_QUESTIONS:
        db.add(CheckinQuestion(procedure_type="ALL", key=key, text=txt, answer_type=typ, options=opts, min_value=mn,
                               max_value=mx, unit=unit, required=req, sort_order=order, help_text=help_))
    for proc, key, txt, typ, order in PROCEDURE_QUESTIONS:
        opts = [{"value": "GOOD", "label": "Good"}, {"value": "FAIR", "label": "Fair"},
                {"value": "POOR", "label": "Poor / not eating"}] if typ == "CHOICE" else []
        db.add(CheckinQuestion(procedure_type=proc, key=key, text=txt, answer_type=typ, options=opts, required=False,
                               sort_order=order))

    # ----- warning protocols (surgeon approved) + one DRAFT revision to show governance
    surgeon = users["doctor@example.com"]
    for rule_id, name, sev, cat, cond, minutes, team, msg, desc in PROTOCOLS:
        db.add(WarningProtocol(rule_id=rule_id, version=1, name=name, description=desc, severity=sev, category=cat,
                               condition=cond, response_minutes=minutes, assigned_team=team, patient_message=msg,
                               status="APPROVED", approved_by_id=surgeon.id, approved_at=now() - timedelta(days=60)))
    db.add(WarningProtocol(rule_id="RED-FEVER", version=2, name="Fever ≥ 100.9°F (proposed)", severity="RED",
                           category="CLINICAL", condition=P("temperature_f", ">=", 100.9), response_minutes=15,
                           assigned_team="NURSE", patient_message=RED_PATIENT_MSG, status="DRAFT",
                           description="Proposed lower threshold — awaiting surgeon approval. Not active."))

    # ----- knowledge documents
    docs_by_key: dict[str, Document] = {}
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        meta, body = parse_frontmatter(path.read_text())
        approver = users.get(meta.get("approver", ""))
        status = meta.get("status", "PENDING")
        doc = Document(
            document_key=meta["document_key"], version=1, title=meta["title"], doc_type=meta["doc_type"],
            authority=meta["authority"], author=meta["author"], procedure_type=meta.get("procedure_type", "ALL"),
            patient_population=meta.get("patient_population", "Adult post-surgical"), approval_status=status,
            approved_by_id=approver.id if approver and status == "APPROVED" else None,
            approved_at=now() - timedelta(days=45) if status == "APPROVED" else None,
            effective_date=date.fromisoformat(meta["effective_date"]) if meta.get("effective_date")
            else today - timedelta(days=45),
            expiry_date=date.fromisoformat(meta["expiry_date"]) if meta.get("expiry_date") else None,
            is_active=status == "APPROVED", content=body.strip(), checksum=checksum(body),
            storage_uri=f"s3://recovery-companion-documents/{meta['document_key']}/v1",
            uploaded_by_id=users["admin@example.com"].id,
        )
        db.add(doc)
        db.flush()
        index_document(db, doc)
        docs_by_key[doc.document_key] = doc

    for title, summary, proc, phase, doc_key, body in EDUCATION:
        db.add(EducationContent(title=title, summary=summary, procedure_type=proc, phase=phase, body=body,
                                document_id=docs_by_key[doc_key].id if doc_key in docs_by_key else None,
                                reading_minutes=2 + len(body) // 400))
    db.flush()

    # ----- patients
    nurses = [users["nurse@example.com"], users["nurse2@example.com"]]
    agent = CheckinAnalysisAgent()
    created_patients: dict[str, Patient] = {}
    for i, (first, last, sex, proc, day, scenario, login) in enumerate(PATIENTS):
        proc_name, surgeon_email, prog = PROCEDURES[proc]
        surgeon_u = users[surgeon_email]
        puser = None
        if login:
            puser = User(email=login, full_name=f"{first} {last}", role_id=roles[Role.PATIENT].id, password_hash=pw,
                         phone=f"+1-555-02{i:02d}")
            db.add(puser)
            db.flush()
        surgery = today - timedelta(days=day)
        p = Patient(user_id=puser.id if puser else None, program_id=programs[prog].id, mrn=f"SYN-{100200 + i}",
                    first_name=first, last_name=last, sex=sex,
                    date_of_birth=date(1946 + rng.randint(0, 40), rng.randint(1, 12), rng.randint(1, 28)),
                    phone=f"+1-555-02{i:02d}", email=login or f"{first.lower()}.{last.lower()}@example.org",
                    assigned_nurse_id=nurses[i % 2].id,
                    enrolled_at=datetime.combine(surgery + timedelta(days=1), time(15, 0), tzinfo=UTC))
        db.add(p)
        db.flush()
        created_patients.setdefault(scenario, p)
        ep = SurgicalEpisode(patient_id=p.id, program_id=programs[prog].id, procedure_type=proc,
                             procedure_name=proc_name, surgeon_id=surgeon_u.id,
                             hospital="Synthetic General Hospital", surgery_date=surgery,
                             discharge_date=surgery + timedelta(days=1 if proc != "LAP_CHOLE" else 0))
        db.add(ep)
        db.flush()
        audit.record(db, "PATIENT_ENROLLED", actor=nurses[i % 2], patient_id=p.id,
                     details={"procedure": proc, "synthetic": True})

        # Recovery plan (v1 approved, or pending for the enrollment demo)
        plan = RecoveryPlan(patient_id=p.id, episode_id=ep.id, title=f"30-Day Recovery Plan — {proc_name}")
        db.add(plan)
        db.flush()
        v = RecoveryPlanVersion(plan_id=plan.id, version=1, content=plan_content(proc), created_by_id=nurses[i % 2].id,
                                change_summary="Initial plan from procedure template",
                                status="PENDING_APPROVAL" if scenario == "pending_plan" else "APPROVED",
                                approved_by_id=None if scenario == "pending_plan" else surgeon_u.id,
                                approved_at=None if scenario == "pending_plan" else
                                datetime.combine(surgery, time(18, 0), tzinfo=UTC))
        db.add(v)
        db.flush()
        if v.status == "APPROVED":
            plan.current_version_id = v.id
            generate_tasks(db, v, p.id)

        # Medications
        meds = []
        for m in medications_for(proc, surgeon_email):
            days = m.pop("days", None)
            med = Medication(patient_id=p.id, episode_id=ep.id, start_date=surgery + timedelta(days=1),
                             end_date=surgery + timedelta(days=days) if days else surgery + timedelta(days=30),
                             prescriber=surgeon_u.full_name,
                             guidance_approved_by=surgeon_u.full_name
                             if m.get("missed_dose_guidance") else None, **m)
            db.add(med)
            meds.append(med)
        db.flush()

        # Medication history: last 3 days
        miss_rate = 0.35 if scenario == "med_adherence" else 0.05
        for back in range(3, 0, -1):
            d = today - timedelta(days=back)
            if d <= surgery:
                continue
            for med in meds:
                for t in med.schedule_times:
                    hh, mm = map(int, t.split(":"))
                    status = "MISSED" if rng.random() < miss_rate else ("SKIPPED" if rng.random() < 0.02 else "TAKEN")
                    db.add(MedicationEvent(medication_id=med.id, patient_id=p.id,
                                           scheduled_for=datetime.combine(d, time(hh, mm), tzinfo=UTC), status=status,
                                           recorded_at=datetime.combine(d, time(hh, mm), tzinfo=UTC) + timedelta(minutes=20),
                                           recorded_by_id=puser.id if puser else None))
        # Today's earlier doses for the demo patient
        if scenario == "normal_demo":
            for med in meds:
                for t in med.schedule_times:
                    hh, mm = map(int, t.split(":"))
                    sched = datetime.combine(today, time(hh, mm), tzinfo=UTC)
                    if sched < now() - timedelta(hours=1):
                        db.add(MedicationEvent(medication_id=med.id, patient_id=p.id, scheduled_for=sched,
                                               status="TAKEN", recorded_by_id=puser.id if puser else None))

        # Appointments
        ortho = proc != "LAP_CHOLE"
        appts = [
            ("PHYSICAL_THERAPY" if ortho else "PHONE_CHECK", "Synthetic PT Associates" if ortho else "Nurse line",
             "120 Example Ave, Suite 4" if ortho else "Telephone", surgery + timedelta(days=6 if ortho else 2), time(10, 0)),
            ("POST_OP_VISIT", surgeon_u.full_name, "Synthetic General Hospital, Clinic B",
             surgery + timedelta(days=14), time(14, 30)),
            ("WOUND_CHECK", "Clinic Nurse", "Synthetic General Hospital, Clinic B", surgery + timedelta(days=10),
             time(9, 15)),
        ]
        for typ, prov, loc, d, t in appts:
            when = datetime.combine(d, t, tzinfo=UTC)
            status = "SCHEDULED"
            if when < now():
                status = "MISSED" if rng.random() < 0.07 else "COMPLETED"
            db.add(Appointment(patient_id=p.id, episode_id=ep.id, appointment_type=typ, provider_name=prov,
                               location=loc, scheduled_at=when, status=status,
                               transportation_status="CONFIRMED" if status != "SCHEDULED" else "UNKNOWN"))
        db.flush()

        # Check-in history (days after discharge up to yesterday)
        start_day = (ep.discharge_date - surgery).days
        for d_ in range(start_day, day):
            d = surgery + timedelta(days=d_)
            if scenario == "missed_checkins" and d_ >= day - 2:
                continue  # last two days missed → scheduler records MISSED + AMBER alert
            if scenario not in ("missed_checkins",) and rng.random() < 0.12 and d_ < day - 2:
                db.add(Checkin(patient_id=p.id, episode_id=ep.id, checkin_date=d, recovery_day=d_, status="MISSED"))
                continue
            ans = normal_answers(rng, d_, proc)
            if scenario == "amber_swelling" and d_ == day - 1:
                ans["swelling"] = "WORSE"
            outcome = agent.submit(db, p, puser or nurses[0], ans, on=d)
            outcome.checkin.submitted_at = datetime.combine(d, time(8, rng.randint(0, 59)), tzinfo=UTC)
        db.flush()

        # Today's scenario-specific check-ins (go through the real rules engine)
        actor = puser or nurses[0]
        if scenario == "red_fever_wound":
            agent.submit(db, p, actor, normal_answers(rng, day, proc) | {
                "pain_score": 7, "pain_trend": "WORSE", "temperature": 101.8, "wound_appearance": "MORE_RED",
                "concern": "Knee feels hot and the redness is spreading."})
        elif scenario == "amber_pain":
            agent.submit(db, p, actor, normal_answers(rng, day, proc) | {"pain_score": 5, "pain_trend": "WORSE"})
        elif scenario == "med_adherence":
            agent.submit(db, p, actor, normal_answers(rng, day, proc) | {"medication_adherence": "MISSED_SOME"})
        elif scenario == "resolved_emergency":
            out = agent.submit(db, p, actor, normal_answers(rng, day, proc) | {"new_symptoms": ["SHORTNESS_OF_BREATH"]},
                               on=today - timedelta(days=1))
            _resolve_history(db, out.alerts, nurses[0], users["doctor@example.com"], minutes_to_contact=6,
                             escalate=True, back_days=1)
        elif scenario == "resolved_red":
            out = agent.submit(db, p, actor, normal_answers(rng, day, proc) | {"temperature": 101.2},
                               on=today - timedelta(days=3))
            _resolve_history(db, out.alerts, nurses[1], None, minutes_to_contact=rng.choice([9, 12, 22]),
                             escalate=False, back_days=3)
        elif scenario in ("normal_demo", "normal_demo2", "pending_plan"):
            pass  # demo patients check in live
        elif scenario in ("transport", "med_question"):
            agent.submit(db, p, actor, normal_answers(rng, day, proc))
        elif scenario == "normal" and rng.random() < 0.6:
            agent.submit(db, p, actor, normal_answers(rng, day, proc))

        if scenario == "transport":
            appt = db.scalars(select(Appointment).where(Appointment.patient_id == p.id,
                                                        Appointment.status == "SCHEDULED")
                              .order_by(Appointment.scheduled_at)).first()
            appt.transportation_status = "NEEDS_HELP"
            appt.transportation_note = "My daughter works that day and I can't drive yet."
            from agents.alerting import AlertEscalationAgent

            AlertEscalationAgent().from_policy(
                db, p, "APPT-TRANSPORT", f"Transportation needed for {appt.appointment_type.replace('_', ' ').lower()} "
                                         f"on {appt.scheduled_at:%b %d}",
                [{"fact": "transportation_status", "actual": "NEEDS_HELP", "appointment_id": str(appt.id)}],
                source="APPOINTMENT")

        if scenario == "med_question":
            from agents.orchestrator import RecoveryAssistantOrchestrator
            from ai.router import ModelRouter
            from app.core.config import get_settings

            offline = ModelRouter(get_settings())
            offline.settings = offline.settings.model_copy(update={"llm_provider": "extractive"})
            RecoveryAssistantOrchestrator(offline).ask(
                db, puser, p, "Can I take ibuprofen with my blood thinner instead of acetaminophen?")

    db.flush()

    # Caregiver authorizations (scenario 7)
    jordan = created_patients["normal_demo"]
    cg = Caregiver(user_id=users["caregiver@example.com"].id, patient_id=jordan.id, relationship_to_patient="Spouse")
    cg.permissions = [CaregiverPermission(scope=s) for s in ("RECOVERY_STATUS", "TASKS", "REMINDERS", "PROGRESS")]
    db.add(cg)
    carol = created_patients["normal_demo2"]
    cg2 = Caregiver(user_id=users["caregiver@example.com"].id, patient_id=carol.id, relationship_to_patient="Neighbor",
                    status="REVOKED", revoked_at=now() - timedelta(days=2))
    cg2.permissions = [CaregiverPermission(scope="PROGRESS", revoked_at=now() - timedelta(days=2))]
    db.add(cg2)
    audit.record(db, "CAREGIVER_AUTHORIZED", actor=db.get(User, jordan.user_id), patient_id=jordan.id,
                 details={"caregiver": "caregiver@example.com", "scopes": ["RECOVERY_STATUS", "TASKS", "REMINDERS",
                                                                           "PROGRESS"]})

    # Missed check-in detection (scenario 2/“Mary Smith”)
    detect_missed_checkins(db)
    db.flush()
    from app.services.integrations import ensure_sources

    ensure_sources(db)
    return {"patients": len(PATIENTS), "documents": len(docs_by_key), "protocols": len(PROTOCOLS) + 1,
            "alerts": db.query(Alert).count()}


def _resolve_history(db: Session, alerts: list[Alert], nurse: User, surgeon: User | None, minutes_to_contact: int,
                     escalate: bool, back_days: int) -> None:
    """Back-dated alert lifecycle so analytics (time-to-contact) have history."""
    for a in alerts:
        base = now() - timedelta(days=back_days, hours=2)
        a.created_at = base
        a.due_at = base + timedelta(minutes=a.required_response_minutes)
        alert_svc.acknowledge(db, a, nurse, "Reviewing check-in")
        a.acknowledged_at = base + timedelta(minutes=max(1, minutes_to_contact - 3))
        alert_svc.record_contact(db, a, nurse, "PHONE", "REACHED", "Spoke with patient; symptoms reviewed.")
        a.first_contact_at = base + timedelta(minutes=minutes_to_contact)
        if escalate and surgeon:
            esc = alert_svc.escalate(db, a, nurse, "SURGEON", "Patient sent to ED for evaluation per protocol.")
            esc.status, esc.response_note = "COMPLETED", "Reviewed ED note. Follow up in clinic."
            esc.responded_at = base + timedelta(minutes=50)
        alert_svc.resolve(db, a, nurse, "Patient evaluated; plan of care reviewed with patient.", "RESOLVED_CONTACTED")
        a.resolved_at = base + timedelta(hours=1)
    for act in db.scalars(select(CareTeamAction).where(CareTeamAction.alert_id.in_([a.id for a in alerts]))):
        act.created_at = act.created_at - timedelta(days=back_days)


def is_empty(db: Session) -> bool:
    return db.scalars(select(User.id)).first() is None


def reset_schema() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    init_schema(engine)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="drop all data and reseed")
    args = parser.parse_args()
    if args.reset:
        reset_schema()
    else:
        init_schema()
    db = SessionLocal()
    try:
        if not is_empty(db):
            print("Database already seeded (use --reset to reseed).")
            return
        result = seed(db)
        db.commit()
        print(f"Seeded synthetic data: {result}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
