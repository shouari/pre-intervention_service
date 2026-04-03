import io
import json
import re
import textwrap
from datetime import datetime
from typing import Any, Dict, List

import streamlit as st

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem
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
    "Réseau",
    "Wi-Fi",
    "Unifi",
    "Control4",
    "Crestron",
    "Hikvision",
    "Audio",
    "Vidéo",
    "Caméras",
    "Intercom",
    "Autre",
]

RISK_OPTIONS = [
    "IP inconnues",
    "Documentation incomplète",
    "Configuration ancienne",
    "Dépendance réseau critique",
    "Accès incertain",
    "Troubleshooting élargi possible",
    "Pièces/configuration potentiellement manquantes",
    "Autre",
]

CONFIDENCE_OPTIONS = [
    "Faible",
    "Moyen",
    "Élevé",
]


# =========================================================
# HELPERS
# =========================================================
def init_state() -> None:
    defaults = {
        "client_name": "",
        "address": "",
        "contact_name": "",
        "contact_phone": "",
        "scheduled_datetime": None,
        "assigned_technician": "",
        "intervention_goal": "",
        "reported_issue": "",
        "context_notes": "",
        "systems_present": [],
        "other_system": "",
        "last_technician": "",
        "attempts_done": "",
        "attempts_result": "",
        "site_constraints": "",
        "nas_main_path": "",
        "nas_other_paths": "",
        "work_docs": [],
        "selected_risks": [],
        "other_risk": "",
        "hypothesis_1": "",
        "hypothesis_2": "",
        "hypothesis_3": "",
        "priority_checks": "",
        "action_plan": "",
        "tools_access_needed": "",
        "confidence_level": "Moyen",
        "ai_summary": "",
        "ai_hypotheses": [],
        "ai_priority_checks": [],
        "ai_risks": [],
        "ai_tools_access_needed": [],
        "ai_missing_information": [],
        "ai_raw_json": "",
        "status": "Brouillon",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


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
    risks = list(st.session_state.selected_risks)
    if "Autre" in risks:
        risks = [r for r in risks if r != "Autre"]
        if clean_text(st.session_state.other_risk):
            risks.append(clean_text(st.session_state.other_risk))
    return risks


def normalize_systems() -> List[str]:
    systems = list(st.session_state.systems_present)
    if "Autre" in systems:
        systems = [s for s in systems if s != "Autre"]
        if clean_text(st.session_state.other_system):
            systems.append(clean_text(st.session_state.other_system))
    return systems


def work_docs_summary(files: List[Any]) -> List[Dict[str, Any]]:
    docs = []
    for f in files:
        docs.append({
            "name": f.name,
            "type": getattr(f, "type", ""),
            "size": getattr(f, "size", None),
        })
    return docs


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
                pages = []
                for page in reader.pages[:8]:
                    pages.append(page.extract_text() or "")
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
            "assigned_technician": clean_text(st.session_state.assigned_technician),
            "intervention_goal": clean_text(st.session_state.intervention_goal),
        },
        "probleme": {
            "reported_issue": clean_text(st.session_state.reported_issue),
            "context_notes": clean_text(st.session_state.context_notes),
        },
        "technique": {
            "systems_present": normalize_systems(),
            "last_technician": clean_text(st.session_state.last_technician),
            "attempts_done": clean_text(st.session_state.attempts_done),
            "attempts_result": clean_text(st.session_state.attempts_result),
            "site_constraints": clean_text(st.session_state.site_constraints),
            "nas_main_path": clean_text(st.session_state.nas_main_path),
            "nas_other_paths": clean_text(st.session_state.nas_other_paths),
            "work_docs": work_docs_summary(st.session_state.work_docs),
        },
        "reflexion": {
            "risks": normalize_risks(),
            "hypotheses": [
                clean_text(st.session_state.hypothesis_1),
                clean_text(st.session_state.hypothesis_2),
                clean_text(st.session_state.hypothesis_3),
            ],
            "priority_checks": split_lines(st.session_state.priority_checks),
            "action_plan": split_lines(st.session_state.action_plan),
            "tools_access_needed": split_lines(st.session_state.tools_access_needed),
            "confidence_level": st.session_state.confidence_level,
        },
        "ai_output": {
            "summary": clean_text(st.session_state.ai_summary),
            "hypotheses": st.session_state.ai_hypotheses,
            "priority_checks": st.session_state.ai_priority_checks,
            "risks": st.session_state.ai_risks,
            "tools_or_access_needed": st.session_state.ai_tools_access_needed,
            "missing_information": st.session_state.ai_missing_information,
            "raw_json": clean_text(st.session_state.ai_raw_json),
        },
    }
    payload["reflexion"]["hypotheses"] = [h for h in payload["reflexion"]["hypotheses"] if h]
    return payload


def report_markdown(payload: Dict[str, Any]) -> str:
    mandat = payload["mandat"]
    probleme = payload["probleme"]
    technique = payload["technique"]
    reflexion = payload["reflexion"]

    lines = []
    lines.append("# Rapport pré-intervention")
    lines.append("")
    lines.append("## Mandat")
    lines.append(f"**Client** : {mandat['client_name'] or '-'}")
    lines.append(f"**Adresse** : {mandat['address'] or '-'}")
    lines.append(f"**Contact** : {mandat['contact_name'] or '-'}")
    lines.append(f"**Téléphone** : {mandat['contact_phone'] or '-'}")
    lines.append(f"**Date / heure** : {mandat['scheduled_datetime'] or '-'}")
    lines.append(f"**Technicien assigné** : {mandat['assigned_technician'] or '-'}")
    lines.append(f"**Objectif** : {mandat['intervention_goal'] or '-'}")
    lines.append("")

    lines.append("## Problème rapporté")
    lines.append(probleme["reported_issue"] or "-")
    lines.append("")

    lines.append("## Contexte utile")
    lines.append(probleme["context_notes"] or "-")
    lines.append("")

    lines.append("## Systèmes présents")
    lines.append(", ".join(technique["systems_present"]) if technique["systems_present"] else "-")
    lines.append("")

    lines.append("## Tentatives déjà faites")
    lines.append(technique["attempts_done"] or "-")
    lines.append("")

    lines.append("## Résultat des tentatives")
    lines.append(technique["attempts_result"] or "-")
    lines.append("")

    lines.append("## Contraintes sur place")
    lines.append(technique["site_constraints"] or "-")
    lines.append("")

    lines.append("## Chemins utiles")
    lines.append(f"**NAS principal** : {technique['nas_main_path'] or '-'}")
    if technique["nas_other_paths"]:
        lines.append("")
        lines.append("**Autres chemins / références** :")
        lines.extend([f"- {x}" for x in split_lines(technique["nas_other_paths"])])
    lines.append("")

    lines.append("## Risques")
    if reflexion["risks"]:
        lines.extend([f"- {r}" for r in reflexion["risks"]])
    else:
        lines.append("-")
    lines.append("")

    lines.append("## Hypothèses")
    if reflexion["hypotheses"]:
        lines.extend([f"- {h}" for h in reflexion["hypotheses"]])
    else:
        lines.append("-")
    lines.append("")

    lines.append("## Vérifications prioritaires")
    if reflexion["priority_checks"]:
        lines.extend([f"- {item}" for item in reflexion["priority_checks"]])
    else:
        lines.append("-")
    lines.append("")

    lines.append("## Plan d'action")
    if reflexion["action_plan"]:
        lines.extend([f"- {item}" for item in reflexion["action_plan"]])
    else:
        lines.append("-")
    lines.append("")

    lines.append("## Outils / accès à prévoir")
    if reflexion["tools_access_needed"]:
        lines.extend([f"- {item}" for item in reflexion["tools_access_needed"]])
    else:
        lines.append("-")
    lines.append("")

    lines.append(f"**Niveau de certitude** : {reflexion['confidence_level'] or '-'}")
    return "\n".join(lines)


def generate_pdf(payload: Dict[str, Any]) -> bytes:
    if not REPORTLAB_AVAILABLE:
        raise RuntimeError("ReportLab n'est pas installé.")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    heading = styles["Heading2"]
    body = styles["BodyText"]
    body.fontName = "Helvetica"
    body.fontSize = 9.5
    body.leading = 13

    small = ParagraphStyle(
        "Small",
        parent=body,
        fontSize=8.5,
        leading=11,
        spaceAfter=4,
    )

    story = []
    mandat = payload["mandat"]
    probleme = payload["probleme"]
    technique = payload["technique"]
    reflexion = payload["reflexion"]

    story.append(Paragraph("Rapport pré-intervention", title_style))
    story.append(Spacer(1, 6))

    intro_lines = [
        f"<b>Client :</b> {mandat['client_name'] or '-'}",
        f"<b>Adresse :</b> {mandat['address'] or '-'}",
        f"<b>Contact :</b> {mandat['contact_name'] or '-'}",
        f"<b>Téléphone :</b> {mandat['contact_phone'] or '-'}",
        f"<b>Date / heure :</b> {mandat['scheduled_datetime'] or '-'}",
        f"<b>Technicien :</b> {mandat['assigned_technician'] or '-'}",
        f"<b>Objectif :</b> {mandat['intervention_goal'] or '-'}",
    ]
    for line in intro_lines:
        story.append(Paragraph(line, body))
    story.append(Spacer(1, 8))

    def add_section(title: str, text: str) -> None:
        story.append(Paragraph(title, heading))
        story.append(Paragraph((text or "-").replace("\n", "<br/>"), body))
        story.append(Spacer(1, 5))

    def add_bullets(title: str, items: List[str]) -> None:
        story.append(Paragraph(title, heading))
        if items:
            flow = ListFlowable(
                [ListItem(Paragraph(item, small)) for item in items],
                bulletType="bullet",
                leftIndent=14,
            )
            story.append(flow)
        else:
            story.append(Paragraph("-", body))
        story.append(Spacer(1, 5))

    add_section("Problème rapporté", probleme["reported_issue"])
    add_section("Contexte utile", probleme["context_notes"])
    add_section("Systèmes présents", ", ".join(technique["systems_present"]) if technique["systems_present"] else "-")
    add_section("Tentatives déjà faites", technique["attempts_done"])
    add_section("Résultat des tentatives", technique["attempts_result"])
    add_section("Contraintes sur place", technique["site_constraints"])
    add_section(
        "Chemins utiles",
        "\n".join(
            [f"NAS principal : {technique['nas_main_path'] or '-'}"] +
            split_lines(technique["nas_other_paths"])
        )
    )
    add_bullets("Risques", reflexion["risks"])
    add_bullets("Hypothèses", reflexion["hypotheses"])
    add_bullets("Vérifications prioritaires", reflexion["priority_checks"])
    add_bullets("Plan d'action", reflexion["action_plan"])
    add_bullets("Outils / accès à prévoir", reflexion["tools_access_needed"])
    add_section("Niveau de certitude", reflexion["confidence_level"])

    doc.build(story)
    return buffer.getvalue()


def build_ai_messages(payload: Dict[str, Any], doc_text: str) -> str:
    generic_payload = {
        "objectif": payload["mandat"]["intervention_goal"],
        "probleme_rapporte": payload["probleme"]["reported_issue"],
        "contexte_facultatif": payload["probleme"]["context_notes"],
        "systemes_presents": payload["technique"]["systems_present"],
        "tentatives_deja_faites": payload["technique"]["attempts_done"],
        "resultat_tentatives": payload["technique"]["attempts_result"],
        "contraintes_sur_place": payload["technique"]["site_constraints"],
        "risques_deja_identifies": payload["reflexion"]["risks"],
        "notes_docs_extraits": doc_text,
    }
    return json.dumps(generic_payload, ensure_ascii=False, indent=2)


def run_ai_analysis(payload: Dict[str, Any], doc_text: str) -> Dict[str, Any]:
    if not OPENAI_AVAILABLE:
        raise RuntimeError("Le package openai n'est pas installé.")

    api_key = st.secrets.get("OPENAI_API_KEY") or st.session_state.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("Aucune clé API OpenAI disponible dans st.secrets['OPENAI_API_KEY'].")

    client = OpenAI(api_key=api_key)

    system_prompt = textwrap.dedent(
        """
        Tu es un assistant de préparation d'interventions techniques pour appels de service résidentiels ou PME légères.
        Tu aides à structurer la réflexion avant l'intervention.

        Règles impératives :
        - N'invente jamais de faits spécifiques au client.
        - Utilise seulement les informations fournies.
        - Si une information manque, signale-la dans missing_information.
        - Reste générique, prudent et concret.
        - Les suggestions doivent être exploitables par un technicien terrain.
        - Priorise les hypothèses probables et les vérifications à forte valeur.
        - Ne donne pas d'informations confidentielles, ne reformule pas de mots de passe ou secrets.
        - Retourne uniquement un JSON valide respectant exactement le schéma demandé.
        """
    ).strip()

    user_prompt = (
        "Analyse ce cas de préparation d'appel de service. "
        "Propose un résumé, 3 à 5 hypothèses plausibles, des vérifications prioritaires, des risques, les outils/accès à prévoir et les informations manquantes.\n\n"
        f"CONTEXTE:\n{build_ai_messages(payload, doc_text)}"
    )

    schema = {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "hypotheses": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 0,
                "maxItems": 5,
            },
            "priority_checks": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 0,
                "maxItems": 7,
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
                "maxItems": 6,
            },
            "missing_information": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 0,
                "maxItems": 6,
            },
            "confidence_level": {
                "type": "string",
                "enum": ["Faible", "Moyen", "Élevé"],
            },
        },
        "required": [
            "summary",
            "hypotheses",
            "priority_checks",
            "risks",
            "tools_or_access_needed",
            "missing_information",
            "confidence_level",
        ],
        "additionalProperties": False,
    }

    response = client.responses.create(
        model="gpt-5-mini",
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "pre_intervention_analysis",
                "schema": schema,
                "strict": True,
            }
        },
    )

    parsed = json.loads(response.output_text)
    return parsed


# =========================================================
# INIT
# =========================================================
init_state()


# =========================================================
# TOP BAR
# =========================================================
st.title("🛠️ Préparation d'appel de service")
st.caption(
    "Standardiser la préparation, réduire la charge cognitive et générer un rapport pré-intervention PDF clair pour le technicien."
)

score = completion_score()
status = "Brouillon"
if score >= 85:
    status = "Prêt pour PDF"
elif score >= 55:
    status = "Prêt pour révision"
st.session_state.status = status

c1, c2, c3 = st.columns([2, 2, 3])
c1.metric("Complétion", f"{score}%")
c2.metric("Statut", status)
c3.progress(score / 100)


# =========================================================
# LAYOUT
# =========================================================
left, right = st.columns([1.15, 0.85], gap="large")

with left:
    with st.expander("1) Mandat", expanded=True):
        a, b = st.columns(2)
        with a:
            st.text_input("Nom client *", key="client_name")
            st.text_input("Contact principal", key="contact_name")
            st.text_input("Technicien assigné", key="assigned_technician")
        with b:
            st.text_input("Adresse *", key="address")
            st.text_input("Téléphone", key="contact_phone")
            st.datetime_input("Date / heure prévue", key="scheduled_datetime", value=None)
        st.text_area(
            "Objectif de l'intervention *",
            key="intervention_goal",
            placeholder="Ex. Remplacer le routeur et remettre le système en route",
            height=90,
        )

    with st.expander("2) Problème", expanded=True):
        st.text_area(
            "Problème rapporté *",
            key="reported_issue",
            placeholder="Copier la description du problème telle qu'elle a été rapportée, sans interprétation.",
            height=160,
        )
        st.text_area(
            "Contexte / historique / notes utiles (facultatif)",
            key="context_notes",
            placeholder="Dernière intervention, comportement observé, infos utiles trouvées dans D-Tools ou le NAS, contraintes particulières...",
            height=150,
        )

    with st.expander("3) Environnement technique", expanded=True):
        st.multiselect("Systèmes présents *", SYSTEM_OPTIONS, key="systems_present")
        if "Autre" in st.session_state.systems_present:
            st.text_input("Préciser le système 'Autre'", key="other_system")

        a, b = st.columns(2)
        with a:
            st.text_input("Dernier technicien intervenu", key="last_technician")
            st.text_area("Tentatives déjà faites", key="attempts_done", height=110)
        with b:
            st.text_area("Résultat de ces tentatives", key="attempts_result", height=110)
            st.text_area("Contraintes sur place", key="site_constraints", height=110)

    with st.expander("4) Documentation de travail", expanded=False):
        st.text_input("Chemin NAS principal", key="nas_main_path")
        st.text_area(
            "Autres chemins / références utiles",
            key="nas_other_paths",
            placeholder="Un chemin ou une référence par ligne",
            height=100,
        )
        st.caption("Ces documents servent d'aide-mémoire au préparateur et de contexte pour l'IA. Ils ne font pas partie du livrable final remis au technicien.")
        uploaded = st.file_uploader(
            "Documents de travail (facultatif)",
            type=["pdf", "txt", "docx", "json"],
            accept_multiple_files=True,
        )
        st.session_state.work_docs = uploaded or []
        if st.session_state.work_docs:
            st.markdown("**Fichiers ajoutés**")
            for f in st.session_state.work_docs:
                st.write(f"- {f.name}")

    with st.expander("5) Réflexion structurée", expanded=True):
        st.multiselect("Risques identifiés", RISK_OPTIONS, key="selected_risks")
        if "Autre" in st.session_state.selected_risks:
            st.text_input("Préciser le risque 'Autre'", key="other_risk")

        st.markdown("**Hypothèses**")
        st.text_input("Hypothèse 1", key="hypothesis_1")
        st.text_input("Hypothèse 2", key="hypothesis_2")
        st.text_input("Hypothèse 3", key="hypothesis_3")

        st.text_area(
            "Vérifications prioritaires",
            key="priority_checks",
            placeholder="Une vérification par ligne",
            height=120,
        )
        st.text_area(
            "Plan d'action",
            key="action_plan",
            placeholder="Une action par ligne",
            height=120,
        )
        st.text_area(
            "Outils / accès à prévoir",
            key="tools_access_needed",
            placeholder="Un item par ligne",
            height=100,
        )
        st.radio("Niveau de certitude", CONFIDENCE_OPTIONS, key="confidence_level", horizontal=True)

    with st.expander("6) Assistance IA", expanded=False):
        st.caption(
            "L'analyse IA doit rester générique et non confidentielle. Les suggestions produites sont éditables et ne remplacent pas le jugement humain."
        )
        doc_text = extract_text_from_uploaded_files(st.session_state.work_docs)
        if st.button("Analyser avec IA", use_container_width=True, type="primary"):
            try:
                payload = build_payload()
                result = run_ai_analysis(payload, doc_text)
                st.session_state.ai_summary = result.get("summary", "")
                st.session_state.ai_hypotheses = result.get("hypotheses", [])
                st.session_state.ai_priority_checks = result.get("priority_checks", [])
                st.session_state.ai_risks = result.get("risks", [])
                st.session_state.ai_tools_access_needed = result.get("tools_or_access_needed", [])
                st.session_state.ai_missing_information = result.get("missing_information", [])
                st.session_state.ai_raw_json = json.dumps(result, ensure_ascii=False, indent=2)
                if result.get("confidence_level") in CONFIDENCE_OPTIONS:
                    st.session_state.confidence_level = result["confidence_level"]
                st.success("Analyse IA générée.")
            except Exception as e:
                st.error(f"Analyse IA impossible : {e}")

        if st.session_state.ai_raw_json:
            st.markdown("**Résumé IA**")
            st.info(st.session_state.ai_summary or "-")

            ai1, ai2 = st.columns(2)
            with ai1:
                st.markdown("**Hypothèses suggérées**")
                for item in st.session_state.ai_hypotheses:
                    st.write(f"- {item}")
                st.markdown("**Risques suggérés**")
                for item in st.session_state.ai_risks:
                    st.write(f"- {item}")
            with ai2:
                st.markdown("**Vérifications prioritaires**")
                for item in st.session_state.ai_priority_checks:
                    st.write(f"- {item}")
                st.markdown("**Outils / accès à prévoir**")
                for item in st.session_state.ai_tools_access_needed:
                    st.write(f"- {item}")

            st.markdown("**Informations manquantes**")
            for item in st.session_state.ai_missing_information:
                st.write(f"- {item}")

            c1, c2, c3 = st.columns(3)
            if c1.button("Insérer hypothèses IA"):
                values = st.session_state.ai_hypotheses[:3]
                st.session_state.hypothesis_1 = values[0] if len(values) > 0 else st.session_state.hypothesis_1
                st.session_state.hypothesis_2 = values[1] if len(values) > 1 else st.session_state.hypothesis_2
                st.session_state.hypothesis_3 = values[2] if len(values) > 2 else st.session_state.hypothesis_3
                st.rerun()
            if c2.button("Insérer vérifications IA"):
                st.session_state.priority_checks = "\n".join(st.session_state.ai_priority_checks)
                st.rerun()
            if c3.button("Insérer risques IA"):
                merged = normalize_risks() + [r for r in st.session_state.ai_risks if r not in normalize_risks()]
                st.session_state.selected_risks = [r for r in merged if r in RISK_OPTIONS]
                other = [r for r in merged if r not in RISK_OPTIONS]
                if other:
                    if "Autre" not in st.session_state.selected_risks:
                        st.session_state.selected_risks.append("Autre")
                    st.session_state.other_risk = "; ".join(other)
                st.rerun()

            if st.button("Insérer outils / accès IA"):
                st.session_state.tools_access_needed = "\n".join(st.session_state.ai_tools_access_needed)
                st.rerun()

            with st.expander("Voir le JSON IA brut"):
                st.code(st.session_state.ai_raw_json, language="json")

with right:
    st.subheader("Aperçu du rapport pré-intervention")
    payload = build_payload()
    md = report_markdown(payload)
    st.markdown(
        """
        <style>
        .report-preview {
            background: white;
            color: #111;
            border-radius: 16px;
            padding: 22px;
            border: 1px solid rgba(0,0,0,.08);
            box-shadow: 0 2px 12px rgba(0,0,0,.04);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('<div class="report-preview">', unsafe_allow_html=True)
    st.markdown(md)
    st.markdown("</div>", unsafe_allow_html=True)

    st.divider()
    st.subheader("Actions")

    json_bytes = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    base_name = f"{datetime.now().strftime('%Y-%m-%d')}_{safe_filename(st.session_state.client_name or 'client')}_preintervention"

    st.download_button(
        "Télécharger JSON",
        data=json_bytes,
        file_name=f"{base_name}.json",
        mime="application/json",
        use_container_width=True,
    )

    if REPORTLAB_AVAILABLE:
        try:
            pdf_bytes = generate_pdf(payload)
            st.download_button(
                "Télécharger PDF",
                data=pdf_bytes,
                file_name=f"{base_name}.pdf",
                mime="application/pdf",
                use_container_width=True,
                type="primary",
            )
        except Exception as e:
            st.error(f"PDF non disponible : {e}")
    else:
        st.warning("ReportLab n'est pas installé. Le téléchargement PDF est désactivé.")

    if st.button("Réinitialiser le dossier", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()


# =========================================================
# FOOTER NOTES
# =========================================================
with st.expander("Notes techniques", expanded=False):
    st.markdown(
        """
        **Dépendances recommandées**
        - `streamlit`
        - `reportlab`
        - `openai`
        - `pypdf`
        - `python-docx`

        **Secrets Streamlit**
        Ajouter dans `.streamlit/secrets.toml` :

        ```toml
        OPENAI_API_KEY = "sk-..."
        ```

        **Important**
        - Sur Streamlit Cloud, la persistance locale n'est pas fiable pour du stockage durable.
        - Ce MVP utilise donc `session_state` pendant la session et propose le téléchargement du JSON/PDF.
        - Les documents uploadés servent d'aide au préparateur et de contexte IA ; ils ne sont pas intégrés au livrable PDF.
        """
    )
