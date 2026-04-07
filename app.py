import io
import json
import os
import re
import textwrap
from datetime import datetime
from typing import Any, Dict, List

# Charger .env si présent (python-dotenv optionnel)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import streamlit as st

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem, HRFlowable
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except Exception:
    OPENAI_AVAILABLE = False


# =========================================================
# CONFIG
# =========================================================
st.set_page_config(
    page_title="Préparation d'appel de service",
    page_icon="🛠️",
    layout="wide",
)


# =========================================================
# CONSTANTS
# =========================================================
SYSTEM_OPTIONS = [
    # Réseau / Infrastructure
    "Unifi Networks",
    "Unifi Protect",
    "Unifi Access",
    # Contrôle
    "Control4",
    "Crestron",
    "Lutron",
    "QSC",
    "Logitech",
    # Sécurité / Caméras
    "Hikvision",
    "Luma",
    "Paradox",
    "DSC",
    "CDVI",
    # Autre
    "Autre",
]

# RISK_OPTIONS supprimé — les risques sont maintenant saisis en texte libre

CONFIDENCE_OPTIONS = [
    "Faible",
    "Moyen",
    "Élevé",
]

TECHNICIAN_LIST = [
    "Alexandre Langlois",
    "Blaise Cyr",
    "Matthieu Chizelle",
    "Frederic Chabot",
    "Claude Tremblay",
    "Simon Levesque",
    "Adlane Lamari",
    "Jérémy Arbour",
    "Michael Samaan",
    "Djilali Nait Abdesselam",
    "Eric Pilon",
]


# =========================================================
# HELPERS
# =========================================================
def init_state() -> None:
    defaults = {
        # Mandat
        "client_name": "",
        "address": "",
        "contact_name": "",
        "contact_phone": "",
        "scheduled_datetime": None,
        "assigned_technician": [],
        "service_call": "",
        # Problème
        "intervention_goal": "",
        "reported_issue": "",
        "context_notes": "",
        # Environnement technique
        "systems_present": [],
        "other_system": "",
        "attempts_summary": "",
        "site_constraints": "",
        # Références
        "references_utiles": "",
        "work_docs": [],
        # Réflexion
        "risks_text": "",
        "hypotheses": "",
        "priority_checks": "",
        "action_plan": "",
        "tools_access_needed": "",
        # Buffers d'injection IA (permettent de mettre à jour les widget-keys AVANT leur rendu)
        "_buf_hypotheses": None,
        "_buf_priority_checks": None,
        "_buf_action_plan": None,
        "_buf_risks_text": None,
        "_buf_tools_access_needed": None,
        # IA output
        "ai_summary": "",
        "ai_action_plan": "",
        "ai_hypotheses": [],
        "ai_priority_checks": [],
        "ai_risks": [],
        "ai_tools_access_needed": [],
        "ai_missing_information": [],
        "ai_raw_json": "",
        # Meta
        "confidence_level": "Moyen",
        "status": "Brouillon",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def apply_injection_buffers() -> None:
    """
    Applique les buffers d'injection IA dans les clés de widgets AVANT leur rendu.
    Streamlit autorise la modification d'une clé de widget AVANT que le widget soit instancié.
    """
    mapping = [
        ("_buf_hypotheses",        "hypotheses"),
        ("_buf_priority_checks",   "priority_checks"),
        ("_buf_action_plan",       "action_plan"),
        ("_buf_risks_text",        "risks_text"),
        ("_buf_tools_access_needed", "tools_access_needed"),
    ]
    for buf_key, target_key in mapping:
        if st.session_state.get(buf_key) is not None:
            st.session_state[target_key] = st.session_state[buf_key]
            st.session_state[buf_key] = None


def safe_filename(value: str) -> str:
    value = value.strip() or "dossier"
    value = re.sub(r"[^A-Za-z0-9À-ÿ._ -]", "_", value)
    value = re.sub(r"\s+", "_", value)
    return value[:80]


def clean_text(value: str) -> str:
    return (value or "").strip()


def split_lines(value: str) -> List[str]:
    return [line.strip("-• \t") for line in (value or "").splitlines() if line.strip()]


def format_datetime(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)


def completion_score() -> int:
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


def normalize_risks() -> List[str]:
    """Retourne la liste des risques depuis le champ texte libre."""
    return split_lines(st.session_state.get("risks_text", ""))


def normalize_systems() -> List[str]:
    systems = list(st.session_state.systems_present)
    if "Autre" in systems:
        systems = [s for s in systems if s != "Autre"]
        if clean_text(st.session_state.other_system):
            systems.append(clean_text(st.session_state.other_system))
    return systems


def work_docs_summary(files: List[Any]) -> List[Dict[str, Any]]:
    return [{"name": f.name, "type": getattr(f, "type", ""), "size": getattr(f, "size", None)} for f in files]


def extract_text_from_uploaded_files(files: List[Any], max_chars_per_file: int = 4000) -> str:
    excerpts: List[str] = []
    for f in files:
        name = f.name.lower()
        try:
            content = f.getvalue()
        except Exception:
            continue

        text = ""
        if name.endswith(".txt"):
            text = content.decode("utf-8", errors="ignore")
        elif name.endswith(".json"):
            text = content.decode("utf-8", errors="ignore")
        elif name.endswith(".pdf"):
            try:
                import pypdf
                reader = pypdf.PdfReader(io.BytesIO(content))
                pages = [page.extract_text() or "" for page in reader.pages[:8]]
                text = "\n".join(pages)
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


def build_payload() -> Dict[str, Any]:
    payload = {
        "meta": {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "status": st.session_state.status,
            "completion_score": completion_score(),
        },
        "mandat": {
            "client_name": clean_text(st.session_state.client_name),
            "address": clean_text(st.session_state.address),
            "contact_name": clean_text(st.session_state.contact_name),
            "contact_phone": clean_text(st.session_state.contact_phone),
            "scheduled_datetime": format_datetime(st.session_state.scheduled_datetime),
            "service_call": clean_text(st.session_state.service_call),
            "assigned_technician": ", ".join(st.session_state.assigned_technician) if isinstance(st.session_state.assigned_technician, list) else clean_text(st.session_state.assigned_technician),
            "intervention_goal": clean_text(st.session_state.intervention_goal),
        },
        "probleme": {
            "reported_issue": clean_text(st.session_state.reported_issue),
            "context_notes": clean_text(st.session_state.context_notes),
        },
        "technique": {
            "systems_present": normalize_systems(),
            "attempts_summary": clean_text(st.session_state.attempts_summary),
            "site_constraints": clean_text(st.session_state.site_constraints),
            "references_utiles": clean_text(st.session_state.references_utiles),
            "work_docs": work_docs_summary(st.session_state.work_docs),
        },
        "reflexion": {
            "risks": normalize_risks(),
            "hypotheses": split_lines(st.session_state.hypotheses),
            "priority_checks": split_lines(st.session_state.priority_checks),
            "action_plan": split_lines(st.session_state.action_plan),
            "tools_access_needed": split_lines(st.session_state.tools_access_needed),
            "confidence_level": st.session_state.confidence_level,
        },
        "ai_output": {
            "summary": clean_text(st.session_state.ai_summary),
            "hypotheses": st.session_state.ai_hypotheses,
            "priority_checks": st.session_state.ai_priority_checks,
            "action_plan": split_lines(st.session_state.ai_action_plan),
            "risks": st.session_state.ai_risks,
            "tools_or_access_needed": st.session_state.ai_tools_access_needed,
            "missing_information": st.session_state.ai_missing_information,
            "raw_json": clean_text(st.session_state.ai_raw_json),
        },
    }
    return payload


def report_markdown(payload: Dict[str, Any]) -> str:
    mandat = payload["mandat"]
    probleme = payload["probleme"]
    technique = payload["technique"]
    reflexion = payload["reflexion"]

    lines = []
    lines.append("# Fiche d'intervention")
    lines.append("")

    # ── Mandat ──────────────────────────────────────────
    lines.append("## 📋 Mandat")
    lines.append("")
    lines.append("|  |  |")
    lines.append("|---|---|")
    lines.append(f"| 🏢 **Client** | {mandat['client_name'] or '-'} |")
    lines.append(f"| 🏷️ **Appel #** | {mandat.get('service_call', '') or '-'} |")
    lines.append(f"| 📍 **Adresse** | {mandat['address'] or '-'} |")
    lines.append(f"| 👤 **Contact** | {mandat['contact_name'] or '-'} |")
    lines.append(f"| 📞 **Téléphone** | {mandat['contact_phone'] or '-'} |")
    lines.append(f"| 📅 **Date / heure** | {mandat['scheduled_datetime'] or '-'} |")
    lines.append(f"| 🔧 **Technicien** | {mandat['assigned_technician'] or '-'} |")
    lines.append("")
    lines.append("**🎯 Objectif** :")
    goal_lines = split_lines(mandat['intervention_goal'])
    if goal_lines:
        lines.extend([f"- {item}" for item in goal_lines])
    else:
        lines.append("-")
    lines.append("")

    # ── Problème ─────────────────────────────────────────
    lines.append("## 🔍 Problème rapporté")
    lines.append(probleme["reported_issue"] or "-")
    lines.append("")
    if clean_text(probleme["context_notes"]):
        lines.append("**Contexte / historique**")
        lines.append(probleme["context_notes"])
        lines.append("")

    # ── Environnement ─────────────────────────────────────
    lines.append("## ⚙️ Environnement technique")
    lines.append(f"**Systèmes** : {', '.join(technique['systems_present']) if technique['systems_present'] else '-'}")
    if clean_text(technique["attempts_summary"]):
        lines.append("")
        lines.append("**Tentatives et résultats**")
        lines.append(technique["attempts_summary"])
    if clean_text(technique["site_constraints"]):
        lines.append("")
        lines.append(f"**Contraintes sur place** : {technique['site_constraints']}")
    lines.append("")

    # ── Références ───────────────────────────────────────
    if clean_text(technique["references_utiles"]):
        lines.append("## 📁 Références utiles")
        lines.extend([f"- {x}" for x in split_lines(technique["references_utiles"])])
        lines.append("")

    # ── Risques ──────────────────────────────────────────
    if reflexion["risks"]:
        lines.append("## ⚠️ Risques identifiés")
        lines.extend([f"- {r}" for r in reflexion["risks"]])
        lines.append("")

    # ── Plan ─────────────────────────────────────────────
    lines.append("## ✅ Vérifications prioritaires")
    if reflexion["priority_checks"]:
        lines.extend([f"- {item}" for item in reflexion["priority_checks"]])
    else:
        lines.append("-")
    lines.append("")

    lines.append("## 🔧 Plan d'action")
    if reflexion["action_plan"]:
        lines.extend([f"- {item}" for item in reflexion["action_plan"]])
    else:
        lines.append("-")
    lines.append("")

    if reflexion["hypotheses"]:
        lines.append("## 💡 Hypothèses")
        lines.extend([f"- {h}" for h in reflexion["hypotheses"]])
        lines.append("")

    if reflexion["tools_access_needed"]:
        lines.append("## 🧰 Outils / accès à prévoir")
        lines.extend([f"- {item}" for item in reflexion["tools_access_needed"]])
        lines.append("")

    return "\n".join(lines)


def generate_pdf(payload: Dict[str, Any]) -> bytes:
    if not REPORTLAB_AVAILABLE:
        raise RuntimeError("ReportLab n'est pas installé.")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = styles["Title"]

    heading2 = ParagraphStyle(
        "heading2",
        parent=styles["Heading2"],
        fontSize=11,
        spaceAfter=3,
        spaceBefore=10,
    )
    body = ParagraphStyle(
        "body",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=13,
        spaceAfter=4,
    )
    small = ParagraphStyle(
        "Small",
        parent=body,
        fontSize=8.5,
        leading=11,
        spaceAfter=2,
    )
    label = ParagraphStyle(
        "label",
        parent=body,
        fontName="Helvetica-Bold",
        fontSize=9.5,
    )

    mandat = payload["mandat"]
    probleme = payload["probleme"]
    technique = payload["technique"]
    reflexion = payload["reflexion"]

    story = []
    story.append(Paragraph("Fiche d'intervention", title_style))
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=1, color="#cccccc"))
    story.append(Spacer(1, 6))

    # ── Mandat (grille 2 colonnes) ──────────────────────
    from reportlab.platypus import Table, TableStyle
    from reportlab.lib import colors

    mandat_data = [
        ["Client",      mandat['client_name'] or '-'],
        ["Appel #",     mandat.get('service_call', '') or '-'],
        ["Adresse",     mandat['address'] or '-'],
        ["Contact",     mandat['contact_name'] or '-'],
        ["Téléphone",   mandat['contact_phone'] or '-'],
        ["Date / heure", mandat['scheduled_datetime'] or '-'],
        ["Technicien",  mandat['assigned_technician'] or '-'],
    ]

    tbl = Table(
        [[Paragraph(f"<b>{r[0]}</b>", body), Paragraph(r[1], body)] for r in mandat_data],
        colWidths=[42 * mm, None],
        hAlign="LEFT",
    )
    tbl.setStyle(TableStyle([
        ("VALIGN",      (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.HexColor("#f5f5f5"), colors.white]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, colors.HexColor("#dddddd")),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 5))
    story.append(Paragraph("<b>Objectif :</b>", body))
    goal_lines = split_lines(mandat['intervention_goal'])
    if goal_lines:
        flow = ListFlowable(
            [ListItem(Paragraph(item, small)) for item in goal_lines],
            bulletType="bullet",
            leftIndent=14,
        )
        story.append(flow)
    else:
        story.append(Paragraph("-", body))
    story.append(Spacer(1, 8))

    def add_section(title: str, text: str) -> None:
        story.append(Paragraph(title, heading2))
        story.append(Paragraph((text or "-").replace("\n", "<br/>"), body))
        story.append(Spacer(1, 4))

    def add_bullets(title: str, items: List[str]) -> None:
        if not items:
            return
        story.append(Paragraph(title, heading2))
        flow = ListFlowable(
            [ListItem(Paragraph(item, small)) for item in items],
            bulletType="bullet",
            leftIndent=14,
        )
        story.append(flow)
        story.append(Spacer(1, 4))

    # ── Problème ─────────────────────────────────────────
    add_section("Problème rapporté", probleme["reported_issue"])
    if clean_text(probleme["context_notes"]):
        add_section("Contexte / historique", probleme["context_notes"])

    # ── Environnement ─────────────────────────────────────
    story.append(Paragraph("Environnement technique", heading2))
    story.append(Paragraph(
        f"<b>Systèmes :</b> {', '.join(technique['systems_present']) if technique['systems_present'] else '-'}",
        body
    ))
    if clean_text(technique["attempts_summary"]):
        story.append(Paragraph("<b>Tentatives et résultats :</b>", label))
        story.append(Paragraph(technique["attempts_summary"].replace("\n", "<br/>"), body))
    if clean_text(technique["site_constraints"]):
        story.append(Paragraph(f"<b>Contraintes sur place :</b> {technique['site_constraints']}", body))
    story.append(Spacer(1, 6))

    # ── Références ───────────────────────────────────────
    if clean_text(technique["references_utiles"]):
        add_bullets("Références utiles", split_lines(technique["references_utiles"]))

    # ── Risques ──────────────────────────────────────────
    add_bullets("Risques identifiés", reflexion["risks"])

    # ── Plan ─────────────────────────────────────────────
    add_bullets("Vérifications prioritaires", reflexion["priority_checks"])
    add_bullets("Plan d'action", reflexion["action_plan"])
    add_bullets("Hypothèses", reflexion["hypotheses"])
    add_bullets("Outils / accès à prévoir", reflexion["tools_access_needed"])

    doc.build(story)
    return buffer.getvalue()


def build_ai_messages(payload: Dict[str, Any], doc_text: str) -> str:
    """
    Construit le contexte technique envoyé à l'IA.
    RÈGLE ABSOLUE : aucune donnée nominative (client, adresse, contact,
    téléphone, technicien, chemins NAS/internes).
    Seules les informations utiles au diagnostic technique sont incluses.
    """
    technical_context = {
        # --- Objectif ---
        "objectif_intervention": payload["mandat"]["intervention_goal"] or "",

        # --- Systèmes en place ---
        "systemes_presents": payload["technique"]["systems_present"],  # ex: ["Unifi Networks", "Control4"]

        # --- Problème ---
        "probleme_rapporte": payload["probleme"]["reported_issue"] or "",
        "contexte_et_historique": payload["probleme"]["context_notes"] or "",

        # --- Ce qui a déjà été tenté ---
        "tentatives_et_resultats": payload["technique"]["attempts_summary"] or "",

        # --- Contraintes terrain ---
        "contraintes_sur_place": payload["technique"]["site_constraints"] or "",

        # --- Réflexion du préparateur (si déjà remplie) ---
        "risques_identifies_preparateur": payload["reflexion"]["risks"],
        "hypotheses_preparateur": payload["reflexion"]["hypotheses"],
        "verifications_preparateur": payload["reflexion"]["priority_checks"],
        "plan_action_preparateur": payload["reflexion"]["action_plan"],
        "outils_acces_preparateur": payload["reflexion"]["tools_access_needed"],

        # --- Contenu des documents joints (texte extrait) ---
        "extraits_documents": doc_text if doc_text else "(aucun document joint)",
    }
    return json.dumps(technical_context, ensure_ascii=False, indent=2)


def run_ai_analysis(payload: Dict[str, Any], doc_text: str) -> Dict[str, Any]:
    if not OPENAI_AVAILABLE:
        raise RuntimeError("Le package openai n'est pas installé.")

    # Priorité : variable d'environnement > st.secrets > session_state
    api_key = (
        os.environ.get("OPENAI_API_KEY")
        or (st.secrets.get("OPENAI_API_KEY") if hasattr(st, "secrets") else None)
        or st.session_state.get("OPENAI_API_KEY", "")
    )
    if not api_key:
        raise RuntimeError(
            "Clé API OpenAI introuvable. "
            "Ajoutez OPENAI_API_KEY dans votre fichier .env ou dans st.secrets."
        )

    client = OpenAI(api_key=api_key)

    system_prompt = textwrap.dedent(
        """
        Tu es un expert en diagnostic et support technique terrain.
        Tu prépares les techniciens AVANT leur intervention.
        Le dossier fourni (JSON) est 100% anonyme (zéro info client).

        L'objectif est d'avoir une analyse ULTRA-CONCISE, directe et lisible d'un seul coup d'œil.
        Élimine tout détail superflu, va droit au but. N'écris que l'essentiel.

        Formats attendus pour les sections:
        1. summary : Résumé en 1 à 2 phrases maximum, factuel et direct.
        2. hypotheses : 2 à 4 causes possibles, très courtes. Moins de 6 mots par ligne (ex: "Alimentation switch défaillante", "Câble réseau coupé").
        3. priority_checks : 3 à 5 actions concises commençant par un verbe (ex: "Vérifier LEDs switch", "Ping passerelle").
        4. action_plan : Étapes courtes et séquentielles, sans fioritures (ex: "1. Reboot équipement X", "2. Tester connectivité").
        5. risks : Mots-clés uniquement (ex: "Coupure service client", "Perte de config").
        6. tools_or_access_needed : Inventaire très bref (ex: "Câble console", "Accès VPN", "Escabeau").
        7. missing_information : Liste très brève des infos bloquantes. Sinon tableau vide [].
        8. confidence_level : "Faible", "Moyen" ou "Élevé".

        RÈGLES ABSOLUES :
        - SOIS BREF. Pas de phrases longues, pas d'explications inutiles. Juste l'action ou l'idée de base.
        - Utilise UNIQUEMENT le contexte JSON.
        - Retourne UNIQUEMENT du JSON valide, rien d'autre.
        """
    ).strip()

    context_json = build_ai_messages(payload, doc_text)

    user_prompt = textwrap.dedent(f"""
        Voici le dossier technique de préparation d'appel de service à analyser.
        Exploite TOUTES les informations disponibles dans chaque champ.
        Si un champ est vide ou absent, ignore-le sans le mentionner sauf s'il est critique
        pour le diagnostic (dans ce cas, l'indiquer dans missing_information).

        DOSSIER TECHNIQUE :
        {context_json}

        Retourne le JSON d'analyse complet selon le schéma défini.
    """).strip()

    schema = {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "hypotheses": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 0,
                "maxItems": 6,
            },
            "priority_checks": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 0,
                "maxItems": 8,
            },
            "action_plan": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 0,
                "maxItems": 10,
            },
            "risks": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 0,
                "maxItems": 6,
            },
            "tools_or_access_needed": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 0,
                "maxItems": 8,
            },
            "missing_information": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 0,
                "maxItems": 8,
            },
            "confidence_level": {
                "type": "string",
                "enum": ["Faible", "Moyen", "Élevé"],
            },
        },
        "required": [
            "summary", "hypotheses", "priority_checks", "action_plan",
            "risks", "tools_or_access_needed", "missing_information", "confidence_level",
        ],
        "additionalProperties": False,
    }

    response = client.chat.completions.create(
        model="gpt-5.4",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
    )

    raw = response.choices[0].message.content or "{}"
    parsed = json.loads(raw)

    # Valider et compléter les champs attendus
    for field in schema["required"]:
        if field not in parsed:
            parsed[field] = [] if field not in ("summary", "confidence_level") else ("" if field == "summary" else "Moyen")

    return parsed


# =========================================================
# INIT + buffers d'injection
# =========================================================
init_state()
apply_injection_buffers()  # DOIT être appelé avant tout rendu de widget


# =========================================================
# TOP BAR
# =========================================================
st.title("🛠️ Préparation d'appel de service")
st.caption("Préparer l'appel, briefer le technicien, générer la fiche d'intervention.")

score = completion_score()
status = "Brouillon"
if score >= 85:
    status = "Prêt pour PDF"
elif score >= 55:
    status = "Prêt pour révision"
st.session_state.status = status

col_score, col_status, col_bar = st.columns([1, 1.4, 3.6])
col_score.metric("Complétion", f"{score}%")
col_status.metric("Statut", status)
col_bar.progress(score / 100)

st.divider()


# =========================================================
# TABS
# =========================================================
tab_prep, tab_tech = st.tabs(["🗂️ Préparateur", "📋 Technicien"])


# ─────────────────────────────────────────────────────────
# ONGLET PRÉPARATEUR
# ─────────────────────────────────────────────────────────
with tab_prep:
    left, right = st.columns([1.1, 0.9], gap="large")

    with left:

        # ── 1) Mandat ────────────────────────────────────
        with st.expander("1) Mandat", expanded=True):
            a, b = st.columns(2)
            with a:
                st.text_input("Client *", key="client_name", placeholder="Nom du client")
                st.text_input("Contact", key="contact_name", placeholder="Prénom Nom")
                st.multiselect("Techniciens assignés", TECHNICIAN_LIST, key="assigned_technician")
            with b:
                st.text_input("Adresse *", key="address")
                st.text_input("Téléphone", key="contact_phone")
                st.datetime_input("Date / heure prévue", key="scheduled_datetime", value=None)
                st.text_input("Appel de service #", key="service_call")
            st.text_area(
                "Objectif de l'intervention *",
                key="intervention_goal",
                placeholder="Ex. Remplacer le routeur défectueux et remettre le réseau en service",
                height=80,
            )

        # ── 2) Problème ──────────────────────────────────
        with st.expander("2) Problème", expanded=True):
            st.text_area(
                "Problème rapporté *",
                key="reported_issue",
                placeholder="Description telle que rapportée par le client — sans interprétation.",
                height=130,
            )
            st.text_area(
                "Contexte / historique (facultatif)",
                key="context_notes",
                placeholder="Dernière intervention, dernier technicien, infos D-Tools, comportement observé...",
                height=110,
            )

        # ── 3) Environnement technique ────────────────────
        with st.expander("3) Environnement technique", expanded=True):
            st.multiselect("Systèmes présents *", SYSTEM_OPTIONS, key="systems_present")
            if "Autre" in st.session_state.systems_present:
                st.text_input("Préciser le système 'Autre'", key="other_system")

            st.text_area(
                "Tentatives et résultats",
                key="attempts_summary",
                placeholder="Qu'est-ce qui a déjà été essayé et quel en a été le résultat ?",
                height=110,
            )
            st.text_input(
                "Contraintes sur place",
                key="site_constraints",
                placeholder="Accès difficile, horaires, présence client requise...",
            )

        # ── 4) Références / Documentation ─────────────────
        with st.expander("4) Références et documents de travail", expanded=False):
            st.text_area(
                "Chemins / références utiles",
                key="references_utiles",
                placeholder="Un chemin NAS, lien, référence par ligne",
                height=100,
            )
            st.caption("Ces informations servent de contexte au préparateur et à l'IA. Elles apparaissent dans la fiche si remplies.")
            uploaded = st.file_uploader(
                "Documents de travail (facultatif)",
                type=["pdf", "txt", "docx", "json"],
                accept_multiple_files=True,
            )
            st.session_state.work_docs = uploaded or []
            if st.session_state.work_docs:
                for f in st.session_state.work_docs:
                    st.caption(f"📎 {f.name}")

        # ── 5) Réflexion structurée ───────────────────────
        with st.expander("5) Réflexion structurée", expanded=True):
            st.text_area(
                "Risques identifiés (un par ligne)",
                key="risks_text",
                placeholder="IP inconnues\nDocumentation incomplète\nAccès incertain\nTroubleshooting élargi possible...",
                height=100,
            )

            st.text_area(
                "Hypothèses (une par ligne)",
                key="hypotheses",
                placeholder="Panne d'alimentation du switch\nConfig VLAN incorrecte\nFirmware obsolète...",
                height=100,
            )
            st.text_area(
                "Vérifications prioritaires (une par ligne)",
                key="priority_checks",
                placeholder="Vérifier les voyants du switch\nPing gateway depuis le rack\n...",
                height=110,
            )
            st.text_area(
                "Plan d'action (une par ligne)",
                key="action_plan",
                placeholder="Redémarrer l'équipement en ordre\nComparer la config actuelle vs backup\n...",
                height=110,
            )
            st.text_area(
                "Outils / accès à prévoir",
                key="tools_access_needed",
                placeholder="Laptop + câble console\nAccès UniFi Controller\nCode alarme client\n...",
                height=90,
            )

        # ── 6) Assistance IA ──────────────────────────────
        with st.expander("6) Assistance IA", expanded=False):
            st.caption(
                "L'analyse IA est générique et non confidentielle. Les suggestions sont éditables et ne remplacent pas le jugement humain."
            )
            doc_text = extract_text_from_uploaded_files(st.session_state.work_docs)
            if st.button("🤖 Analyser avec IA", use_container_width=True, type="primary"):
                with st.spinner("Analyse en cours..."):
                    try:
                        payload = build_payload()
                        result = run_ai_analysis(payload, doc_text)
                        st.session_state.ai_summary = result.get("summary", "")
                        st.session_state.ai_hypotheses = result.get("hypotheses", [])
                        st.session_state.ai_priority_checks = result.get("priority_checks", [])
                        st.session_state.ai_action_plan = "\n".join(result.get("action_plan", []))
                        st.session_state.ai_risks = result.get("risks", [])
                        st.session_state.ai_tools_access_needed = result.get("tools_or_access_needed", [])
                        st.session_state.ai_missing_information = result.get("missing_information", [])
                        st.session_state.ai_raw_json = json.dumps(result, ensure_ascii=False, indent=2)
                        conf = result.get("confidence_level", "")
                        if conf in CONFIDENCE_OPTIONS:
                            st.session_state.confidence_level = conf
                        st.success("✅ Analyse IA générée avec succès.")
                    except Exception as e:
                        st.error(f"Analyse IA impossible : {e}")

            if st.session_state.ai_raw_json:
                # ── Résumé ──────────────────────────────────────
                st.markdown("### 📋 Résumé IA")
                st.info(st.session_state.ai_summary or "-")

                st.divider()

                # ── Hypothèses + Vérifications ───────────────────
                ai1, ai2 = st.columns(2)
                with ai1:
                    st.markdown("**💡 Hypothèses (par probabilité)**")
                    for i, item in enumerate(st.session_state.ai_hypotheses, 1):
                        st.markdown(f"{i}. {item}")

                    st.markdown("**⚠️ Risques identifiés**")
                    for item in st.session_state.ai_risks:
                        st.markdown(f"- {item}")

                with ai2:
                    st.markdown("**✅ Vérifications prioritaires**")
                    for i, item in enumerate(st.session_state.ai_priority_checks, 1):
                        st.markdown(f"{i}. {item}")

                    st.markdown("**🧰 Outils / accès à prévoir**")
                    for item in st.session_state.ai_tools_access_needed:
                        st.markdown(f"- {item}")

                # ── Plan d'action ────────────────────────────────
                if st.session_state.ai_action_plan:
                    st.markdown("**🔧 Plan d'action suggéré**")
                    for i, item in enumerate(split_lines(st.session_state.ai_action_plan), 1):
                        st.markdown(f"{i}. {item}")

                # ── Infos manquantes ─────────────────────────────
                if st.session_state.ai_missing_information:
                    st.markdown("**🔎 Informations manquantes**")
                    for item in st.session_state.ai_missing_information:
                        st.markdown(f"- {item}")

                st.divider()

                # ── Boutons d'insertion ──────────────────────────
                st.caption("Insérer les suggestions IA dans les champs ci-dessus :")
                c1, c2, c3, c4, c5 = st.columns(5)

                if c1.button("↳ Hypothèses", use_container_width=True):
                    existing = clean_text(st.session_state.hypotheses)
                    new_items = "\n".join(st.session_state.ai_hypotheses)
                    st.session_state["_buf_hypotheses"] = (existing + "\n" + new_items).strip() if existing else new_items
                    st.rerun()

                if c2.button("↳ Vérifications", use_container_width=True):
                    existing = clean_text(st.session_state.priority_checks)
                    new_items = "\n".join(st.session_state.ai_priority_checks)
                    st.session_state["_buf_priority_checks"] = (existing + "\n" + new_items).strip() if existing else new_items
                    st.rerun()

                if c3.button("↳ Plan d'action", use_container_width=True):
                    existing = clean_text(st.session_state.action_plan)
                    new_items = clean_text(st.session_state.ai_action_plan)
                    st.session_state["_buf_action_plan"] = (existing + "\n" + new_items).strip() if existing else new_items
                    st.rerun()

                if c4.button("↳ Risques", use_container_width=True):
                    existing = clean_text(st.session_state.risks_text)
                    new_items = "\n".join(
                        r for r in st.session_state.ai_risks
                        if r not in split_lines(existing)
                    )
                    if new_items:
                        st.session_state["_buf_risks_text"] = (existing + "\n" + new_items).strip() if existing else new_items
                        st.rerun()

                if c5.button("↳ Outils", use_container_width=True):
                    existing = clean_text(st.session_state.tools_access_needed)
                    new_items = "\n".join(st.session_state.ai_tools_access_needed)
                    st.session_state["_buf_tools_access_needed"] = (existing + "\n" + new_items).strip() if existing else new_items
                    st.rerun()

                with st.expander("Voir le JSON IA brut"):
                    st.code(st.session_state.ai_raw_json, language="json")

    # ── Aperçu live (colonne droite de l'onglet Préparateur) ──
    with right:
        st.subheader("Aperçu de la fiche")
        payload = build_payload()
        md = report_markdown(payload)
        st.markdown(
            """
            <style>
            .report-preview {
                background: white;
                color: #111;
                border-radius: 14px;
                padding: 20px 24px;
                border: 1px solid rgba(0,0,0,.08);
                box-shadow: 0 2px 12px rgba(0,0,0,.05);
                font-size: 0.9em;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
        st.markdown('<div class="report-preview">', unsafe_allow_html=True)
        st.markdown(md)
        st.markdown("</div>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────
# ONGLET TECHNICIEN
# ─────────────────────────────────────────────────────────
with tab_tech:
    payload = build_payload()
    mandat = payload["mandat"]
    score_now = payload["meta"]["completion_score"]

    # En-tête mission
    if score_now < 40:
        st.warning("⚠️ La fiche est incomplète. Remplissez d'abord les champs obligatoires dans l'onglet Préparateur.")
    elif score_now < 85:
        st.info(f"📝 Fiche en cours de préparation ({score_now}% complétée). Certains champs sont manquants.")
    else:
        st.success("✅ Fiche prête pour l'intervention.")

    # Aperçu propre de la fiche
    md = report_markdown(payload)
    st.markdown(
        """
        <style>
        .tech-report {
            background: white;
            color: #111;
            border-radius: 14px;
            padding: 28px 32px;
            border: 1px solid rgba(0,0,0,.08);
            box-shadow: 0 2px 16px rgba(0,0,0,.06);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('<div class="tech-report">', unsafe_allow_html=True)
    st.markdown(md)
    st.markdown("</div>", unsafe_allow_html=True)

    st.divider()

    # Actions de téléchargement
    st.subheader("Télécharger la fiche")
    base_name = f"{datetime.now().strftime('%Y-%m-%d')}_{safe_filename(st.session_state.client_name or 'client')}_intervention"

    col_pdf, col_json, col_reset = st.columns([2, 2, 1])

    with col_pdf:
        if REPORTLAB_AVAILABLE:
            try:
                pdf_bytes = generate_pdf(payload)
                st.download_button(
                    "📄 Télécharger PDF",
                    data=pdf_bytes,
                    file_name=f"{base_name}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    type="primary",
                )
            except Exception as e:
                st.error(f"PDF non disponible : {e}")
        else:
            st.warning("ReportLab n'est pas installé. Téléchargement PDF désactivé.")

    with col_json:
        json_bytes = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        st.download_button(
            "📦 Télécharger JSON",
            data=json_bytes,
            file_name=f"{base_name}.json",
            mime="application/json",
            use_container_width=True,
        )

    with col_reset:
        if st.button("🔄 Réinitialiser", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
