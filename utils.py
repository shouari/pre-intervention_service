"""
utils.py — Fonctions utilitaires pures (sans dépendance Streamlit).
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Any, List


# ─── Texte ─────────────────────────────────────────────────

def clean_text(value: Any) -> str:
    """Retourne la valeur sous forme de chaîne nettoyée (strip)."""
    return (value or "").strip()


def split_lines(value: str) -> List[str]:
    """Découpe un bloc de texte en lignes non-vides."""
    return [line.strip() for line in (value or "").splitlines() if line.strip()]


def safe_filename(value: str) -> str:
    """Génère un nom de fichier sûr à partir d'une chaîne quelconque."""
    value = (value or "").strip() or "dossier"
    value = re.sub(r"[^A-Za-z0-9À-ÿ._ -]", "_", value)
    value = re.sub(r"\s+", "_", value)
    return value[:80]


# ─── Dates ─────────────────────────────────────────────────

def format_datetime(value: Any) -> str:
    """Formate un objet datetime ou une chaîne ISO en 'YYYY-MM-DD HH:MM'."""
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)


def format_french_date(date_str: str) -> str:
    """Convertit 'YYYY-MM-DD' en '14 avril 2026'."""
    months = {
        "01": "janvier", "02": "février",  "03": "mars",      "04": "avril",
        "05": "mai",     "06": "juin",     "07": "juillet",   "08": "août",
        "09": "septembre","10": "octobre", "11": "novembre",  "12": "décembre",
    }
    try:
        y, m, d = date_str.split("-")
        day = str(int(d))
        if day == "1":
            day = "1er"
        return f"{day} {months[m]} {y}"
    except Exception:
        return date_str


# ─── Documents ─────────────────────────────────────────────

def work_docs_summary(files: List[Any]) -> List[dict]:
    return [
        {"name": f.name, "type": getattr(f, "type", ""), "size": getattr(f, "size", None)}
        for f in files
    ]


def extract_text_from_uploaded_files(files: List[Any], max_chars_per_file: int = 4000) -> str:
    """Extrait le texte brut des fichiers uploadés (txt, json, pdf, docx)."""
    excerpts: List[str] = []
    for f in files:
        name = f.name.lower()
        try:
            content = f.getvalue()
        except Exception:
            continue

        text = ""
        if name.endswith(".txt") or name.endswith(".json"):
            text = content.decode("utf-8", errors="ignore")
        elif name.endswith(".pdf"):
            try:
                import pypdf
                reader = pypdf.PdfReader(io.BytesIO(content))
                text = "\n".join(page.extract_text() or "" for page in reader.pages[:8])
            except Exception:
                text = ""
        elif name.endswith(".docx"):
            try:
                import docx
                doc = docx.Document(io.BytesIO(content))
                text = "\n".join(p.text for p in doc.paragraphs)
            except Exception:
                text = ""

        text = clean_text(text)
        if text:
            excerpts.append(f"### Fichier: {f.name}\n{text[:max_chars_per_file]}")
    return "\n\n".join(excerpts)


# ─── Session-state helpers (import streamlit here to avoid top-level cost) ──

def normalize_systems() -> list:
    import re
    import streamlit as st
    systems = list(st.session_state.systems_present)
    if "Autre" in systems:
        systems = [s for s in systems if s != "Autre"]
        other = (st.session_state.other_system or "").strip()
        if other:
            systems.extend(x.strip() for x in re.split(r"[;,\n]", other) if x.strip())
    return systems


def normalize_risks() -> list:
    import streamlit as st
    return split_lines(st.session_state.get("risks_text", ""))


def completion_score() -> int:
    import streamlit as st
    fields = [
        bool(clean_text(st.session_state.client_name)),
        bool(clean_text(st.session_state.address)),
        bool(clean_text(st.session_state.intervention_goal)),
        bool(clean_text(st.session_state.reported_issue)),
        len(st.session_state.systems_present) > 0,
        bool(clean_text(st.session_state.priority_checks)),
        bool(clean_text(st.session_state.action_plan)),
    ]
    return int(sum(fields) / len(fields) * 100)
