"""
utils.py — Fonctions utilitaires pures (sans dépendance Streamlit).
"""
from __future__ import annotations

import io
import re
import zipfile
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

# Extensions traitées comme texte brut (aucune librairie requise)
_TEXT_EXTENSIONS = (
    ".txt", ".json", ".xml", ".csv", ".log", ".ini", ".cfg",
    ".csp", ".usp", ".lua", ".lut", ".yaml", ".yml",
)

# Archives ZIP (formats propriétaires AV/réseau + zip générique)
_ZIP_EXTENSIONS = (".zip", ".c4p", ".c4z", ".lpz", ".qsys", ".vtz", ".unf")


def work_docs_summary(files: List[Any]) -> List[dict]:
    return [
        {"name": f.name, "type": getattr(f, "type", ""), "size": getattr(f, "size", None)}
        for f in files
    ]


def _extract_from_zip(content: bytes, max_chars: int = 8000) -> str:
    """Extrait le texte lisible d'une archive ZIP (projets Control4, Crestron, QSC, etc.)."""
    TEXT_EXTS = (".xml", ".json", ".txt", ".csv", ".lua", ".csp", ".usp",
                 ".log", ".ini", ".cfg", ".lut", ".yaml", ".yml")
    PRIORITY_NAMES = {
        "project.c4p", "project.xml", "driver.xml", "system.json",
        "config.json", "project.json", "program.json",
    }
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = zf.namelist()
            priority = [n for n in names if n.split("/")[-1].lower() in PRIORITY_NAMES]
            readable = [
                n for n in names
                if n not in priority
                and any(n.lower().endswith(e) for e in TEXT_EXTS)
                and not n.startswith("__")
            ]
            total = ""
            for fname in priority + readable:
                if len(total) >= max_chars:
                    break
                try:
                    data = zf.read(fname)
                    text = data.decode("utf-8", errors="ignore").strip()
                    if text:
                        remaining = max_chars - len(total)
                        total += f"\n\n[{fname}]\n{text[:remaining]}"
                except Exception:
                    continue
            return total.strip()
    except zipfile.BadZipFile:
        return ""


def extract_text_from_uploaded_files(files: List[Any], max_chars_per_file: int = 4000) -> str:
    """Extrait le texte des fichiers uploadés : txt/json/xml/lua/csp, pdf, docx, archives ZIP (c4p, c4z, lpz, qsys…)."""
    excerpts: List[str] = []
    for f in files:
        name = f.name.lower()
        try:
            content = f.getvalue()
        except Exception:
            continue

        text = ""
        if any(name.endswith(e) for e in _TEXT_EXTENSIONS):
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
        elif any(name.endswith(e) for e in _ZIP_EXTENSIONS):
            text = _extract_from_zip(content, max_chars=8000)
        else:
            # Tentative de décodage UTF-8 pour formats inconnus (ex: .smw Crestron)
            try:
                decoded = content.decode("utf-8", errors="ignore")
                printable = sum(c.isprintable() or c in "\n\r\t" for c in decoded)
                if decoded and printable / len(decoded) > 0.70:
                    text = decoded
            except Exception:
                text = ""

        text = clean_text(text)
        # Limite plus généreuse pour les archives (contenu multi-fichiers)
        limit = 8000 if any(name.endswith(e) for e in _ZIP_EXTENSIONS) else max_chars_per_file
        if text:
            excerpts.append(f"### Fichier: {f.name}\n{text[:limit]}")
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
