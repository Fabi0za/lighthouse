"""Seed the eval_questions table in Supabase with example test questions.

The questions below are generic examples for German electrical-installation
documents. Replace them with questions derived from your own ingested corpus —
`required_source_docs` must contain the document UUIDs returned at ingestion.
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.database import DatabaseClient


# Placeholder document IDs — replace with real UUIDs from your `documents` table.
DOC_A = "00000000-0000-0000-0000-000000000001"
DOC_B = "00000000-0000-0000-0000-000000000002"


EVAL_QUESTIONS = [
    {
        "question": "Welcher Mindestquerschnitt gilt für den Schutzleiter, wenn der Außenleiter 16 mm² hat?",
        "question_type": "answerable",
        "expected_answer": "Der Schutzleiter muss mindestens 16 mm² betragen.",
        "required_source_docs": [DOC_A],
        "required_facts": ["Schutzleiter mindestens 16 mm²"],
        "category": "Verkabelung",
    },
    {
        "question": "Welche Schutzart muss ein Zählerschrank im Außenbereich mindestens erfüllen?",
        "question_type": "answerable",
        "expected_answer": "Im Außenbereich ist mindestens IP54 erforderlich.",
        "required_source_docs": [DOC_A],
        "required_facts": ["Mindestens IP54 im Außenbereich"],
        "category": "Messwesen",
    },
    {
        "question": "Ab welcher Anschlussleistung ist eine Anmeldung beim Netzbetreiber erforderlich?",
        "question_type": "answerable",
        "expected_answer": "Ab 3,6 kVA ist eine Anmeldung beim Netzbetreiber erforderlich.",
        "required_source_docs": [DOC_B],
        "required_facts": ["Anmeldepflicht ab 3,6 kVA"],
        "category": "Netzanschluss",
    },
    {
        "question": "Muss eine Notheizung mechanisch gegen unbeabsichtigtes Einschalten gesichert werden?",
        "question_type": "answerable",
        "expected_answer": "Ja, Notheizungen müssen grundsätzlich mechanisch gegen Einschalten gesichert sein.",
        "required_source_docs": [DOC_A],
        "required_facts": ["Mechanische Sicherung ist vorgeschrieben"],
        "category": "Heizung",
    },
    {
        "question": "Welches Anzugsdrehmoment gilt für die AC-Anschlussklemmen laut Betriebsanleitung?",
        "question_type": "answerable",
        "expected_answer": "Die AC-Anschlussklemmen sind mit 2,5 Nm anzuziehen.",
        "required_source_docs": [DOC_B],
        "required_facts": ["2,5 Nm Anzugsdrehmoment"],
        "category": "Installation",
    },
    {
        "question": "Wie viele Batteriemodule können maximal in einem Strang kombiniert werden?",
        "question_type": "answerable",
        "expected_answer": "Es können maximal sechs Batteriemodule pro Strang kombiniert werden.",
        "required_source_docs": [DOC_B],
        "required_facts": ["Maximal sechs Module pro Strang"],
        "category": "Speicher",
    },
    {
        "question": "Wie hoch ist die maximale Kabellänge für das RS-485 Kommunikationskabel zwischen EMS und Wechselrichter?",
        "question_type": "unanswerable",
        "expected_answer": "Diese Information ist nicht in den Dokumenten enthalten.",
        "required_source_docs": [],
        "required_facts": [
            "Die Betriebsanleitung spezifiziert den Kabeltyp, aber keine Längenbegrenzung.",
            "Maximale Leitungslängen für RS-485 werden nicht aufgeführt.",
        ],
        "category": "Unanswerable / Installation",
    },
    {
        "question": "Welche kommunalen Zusatzgebühren fallen bei einem Netzanschluss an?",
        "question_type": "unanswerable",
        "expected_answer": "Diese Information ist nicht in den Dokumenten enthalten.",
        "required_source_docs": [],
        "required_facts": [
            "Die Dokumente verweisen auf kommunale Vorschriften, nennen aber keine Gebühren.",
            "Keine Preistabelle für Zusatzgebühren vorhanden.",
        ],
        "category": "Unanswerable / Gebühren",
    },
]


def seed():
    db = DatabaseClient()

    # Clear existing eval questions for idempotency
    db.client.table("eval_questions").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()

    # Insert all questions
    db.client.table("eval_questions").insert(EVAL_QUESTIONS).execute()

    print(f"Seeded {len(EVAL_QUESTIONS)} eval questions.")


if __name__ == "__main__":
    seed()
