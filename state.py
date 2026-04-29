"""
state.py — Gestion du session_state Streamlit et callbacks.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

import streamlit as st

from config import SYSTEM_OPTIONS
from database import (
    get_pre_intervention,
    get_real_intervention,
    save_pre_intervention,
    upsert_real_intervention,
)
from utils import clean_text, split_lines, format_datetime, normalize_systems


# ─── Initialisation ────────────────────────────────────────

def init_state() -> None:
    defaults: Dict[str, Any] = {
        # Mandat
        "client_name":          "",
        "address":              "",
        "contact_name":         "",
        "contact_phone":        "",
        "scheduled_datetime":   None,
        "assigned_technician":  [],
        "service_call":         "",
        # Problème
        "intervention_goal":    "",
        "reported_issue":       "",
        "history_context":      "",
        # Environnement technique
        "systems_present":      [],
        "other_system":         "",
        "attempts_summary":     "",
        "site_constraints":     "",
        # Références
        "references_utiles":    "",
        "work_docs":            [],
        # Réflexion manuelle
        "risks_text":           "",
        "hypotheses":           "",
        "priority_checks":      "",
        "action_plan":          "",
        "tools_access_needed":  "",
        # Buffers d'injection IA
        "_buf_hypotheses":          None,
        "_buf_priority_checks":     None,
        "_buf_action_plan":         None,
        "_buf_risks_text":          None,
        "_buf_tools_access_needed": None,
        # Sortie IA
        "ai_summary":               "",
        "ai_raisonnement":          "",
        "ai_web_research":          "",
        "ai_action_plan":           "",
        "ai_hypotheses":            [],
        "ai_priority_checks":       [],
        "ai_risks":                 [],
        "ai_tools_access_needed":   [],
        "ai_missing_information":   [],
        "ai_raw_json":              "",
        # Méta
        "confidence_level":             "Moyen",
        "status":                       "Brouillon",
        "current_pre_intervention_id":  None,
        "history_search":               "",
        # Retour terrain
        "real_work_done":   "",
        "real_root_cause":  "",
        # Divers
        "_success_msg":     "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def reset_main_form_state() -> None:
    preserved = {"history_search": st.session_state.get("history_search", "")}
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    init_state()
    for key, value in preserved.items():
        st.session_state[key] = value


# ─── Chargement depuis la DB ───────────────────────────────

def load_payload_into_state(payload: Dict[str, Any], pre_id: Optional[int] = None) -> None:
    mandat    = payload.get("mandat", {})
    probleme  = payload.get("probleme", {})
    technique = payload.get("technique", {})
    reflexion = payload.get("reflexion", {})
    ai_output = payload.get("ai_output", {})

    st.session_state.client_name   = mandat.get("client_name", "")
    st.session_state.address       = mandat.get("address", "")
    st.session_state.contact_name  = mandat.get("contact_name", "")
    st.session_state.contact_phone = mandat.get("contact_phone", "")
    st.session_state.service_call  = mandat.get("service_call", "")
    st.session_state.intervention_goal = mandat.get("intervention_goal", "")

    dt_value = mandat.get("scheduled_datetime", "")
    try:
        st.session_state.scheduled_datetime = datetime.fromisoformat(dt_value) if dt_value else None
    except Exception:
        try:
            st.session_state.scheduled_datetime = datetime.strptime(dt_value, "%Y-%m-%d %H:%M") if dt_value else None
        except Exception:
            st.session_state.scheduled_datetime = None

    assigned = mandat.get("assigned_technician", "")
    st.session_state.assigned_technician = (
        [x.strip() for x in assigned.split(",") if x.strip()]
        if isinstance(assigned, str)
        else assigned
    )

    st.session_state.reported_issue  = probleme.get("reported_issue", "")
    # Compat : history_context peut être dans probleme (ancien) ou technique (nouveau)
    st.session_state.history_context = (
        technique.get("history_context", "")
        or probleme.get("context_notes", "")
    )

    systems = technique.get("systems_present", [])
    known   = [s for s in systems if s in SYSTEM_OPTIONS and s != "Autre"]
    unknown = [s for s in systems if s not in SYSTEM_OPTIONS]
    st.session_state.systems_present   = known + (["Autre"] if unknown else [])
    st.session_state.other_system      = "; ".join(unknown)
    st.session_state.attempts_summary  = technique.get("attempts_summary", "")
    st.session_state.site_constraints  = technique.get("site_constraints", "")
    st.session_state.references_utiles = technique.get("references_utiles", "")
    st.session_state.work_docs         = []

    def to_str(val: Any) -> str:
        if isinstance(val, list):
            return "\n".join(str(x) for x in val)
        return str(val or "")

    st.session_state.risks_text       = to_str(reflexion.get("risks"))
    st.session_state.hypotheses       = to_str(reflexion.get("hypotheses"))
    st.session_state.priority_checks  = to_str(reflexion.get("priority_checks"))
    st.session_state.action_plan      = to_str(reflexion.get("action_plan"))
    st.session_state.tools_access_needed = to_str(reflexion.get("tools_access_needed"))
    st.session_state.confidence_level = reflexion.get("confidence_level", "Moyen")

    st.session_state.ai_summary       = ai_output.get("summary", "")
    st.session_state.ai_hypotheses    = ai_output.get("hypotheses", [])
    st.session_state.ai_priority_checks = ai_output.get("priority_checks", [])
    ai_ap = ai_output.get("action_plan", [])
    st.session_state.ai_action_plan   = "\n".join(ai_ap) if isinstance(ai_ap, list) else ai_ap
    st.session_state.ai_risks         = ai_output.get("risks", [])
    st.session_state.ai_tools_access_needed  = ai_output.get("tools_or_access_needed", [])
    st.session_state.ai_missing_information  = ai_output.get("missing_information", [])
    st.session_state.ai_raw_json      = ai_output.get("raw_json", "") or json.dumps(ai_output, ensure_ascii=False, indent=2)

    st.session_state.current_pre_intervention_id = pre_id


def load_real_intervention_into_state(record: Optional[Dict[str, Any]]) -> None:
    st.session_state.real_work_done  = (record or {}).get("work_done", "")
    st.session_state.real_root_cause = (record or {}).get("real_root_cause", "")


# ─── Build payload ─────────────────────────────────────────

def build_payload() -> Dict[str, Any]:
    from utils import work_docs_summary, completion_score  # import local pour éviter les cycles
    return {
        "meta": {
            "created_at":           datetime.now().isoformat(timespec="seconds"),
            "status":               st.session_state.status,
            "completion_score":     completion_score(),
            "pre_intervention_id":  st.session_state.current_pre_intervention_id,
        },
        "mandat": {
            "client_name":         clean_text(st.session_state.client_name),
            "address":             clean_text(st.session_state.address),
            "contact_name":        clean_text(st.session_state.contact_name),
            "contact_phone":       clean_text(st.session_state.contact_phone),
            "scheduled_datetime":  format_datetime(st.session_state.scheduled_datetime),
            "service_call":        clean_text(st.session_state.service_call),
            "assigned_technician": (
                ", ".join(st.session_state.assigned_technician)
                if isinstance(st.session_state.assigned_technician, list)
                else clean_text(st.session_state.assigned_technician)
            ),
            "intervention_goal": clean_text(st.session_state.intervention_goal),
        },
        "probleme": {
            "reported_issue": clean_text(st.session_state.reported_issue),
        },
        "technique": {
            "systems_present":  normalize_systems(),
            "attempts_summary": clean_text(st.session_state.attempts_summary),
            "site_constraints": clean_text(st.session_state.site_constraints),
            "references_utiles": clean_text(st.session_state.references_utiles),
            "work_docs":        work_docs_summary(st.session_state.work_docs),
            "history_context":  clean_text(st.session_state.get("history_context", "")),
        },
        "reflexion": {
            "risks":             clean_text(st.session_state.risks_text),
            "hypotheses":        clean_text(st.session_state.hypotheses),
            "priority_checks":   clean_text(st.session_state.priority_checks),
            "action_plan":       clean_text(st.session_state.action_plan),
            "tools_access_needed": clean_text(st.session_state.tools_access_needed),
            "confidence_level":  st.session_state.confidence_level,
        },
        "ai_output": {
            "summary":              clean_text(st.session_state.ai_summary),
            "hypotheses":           st.session_state.ai_hypotheses,
            "priority_checks":      st.session_state.ai_priority_checks,
            "action_plan":          split_lines(st.session_state.ai_action_plan),
            "risks":                st.session_state.ai_risks,
            "tools_or_access_needed": st.session_state.ai_tools_access_needed,
            "missing_information":  st.session_state.ai_missing_information,
            "raw_json":             clean_text(st.session_state.ai_raw_json),
        },
    }


# ─── Callbacks ─────────────────────────────────────────────

def apply_injection_buffers() -> None:
    mapping = [
        ("_buf_hypotheses",       "hypotheses"),
        ("_buf_priority_checks",  "priority_checks"),
        ("_buf_action_plan",      "action_plan"),
        ("_buf_risks_text",       "risks_text"),
        ("_buf_tools_access_needed", "tools_access_needed"),
    ]
    for buf_key, target_key in mapping:
        if st.session_state.get(buf_key) is not None:
            st.session_state[target_key] = st.session_state[buf_key]
            st.session_state[buf_key] = None


def load_historical_data_callback(row_id: int) -> None:
    db_row = get_pre_intervention(row_id)
    if db_row:
        payload = json.loads(db_row["payload_json"])
        load_payload_into_state(payload, row_id)
        load_real_intervention_into_state(get_real_intervention(row_id))
        st.session_state._success_msg = f"✅ Pré-intervention #{row_id} chargée."


def reset_main_form_state_callback() -> None:
    reset_main_form_state()
    st.session_state._success_msg = "🆕 Nouveau dossier créé."


def save_real_intervention_callback() -> None:
    current_id = st.session_state.current_pre_intervention_id
    if not current_id:
        st.session_state._success_msg = "⚠️ Aucun dossier chargé. Sauvegardez d'abord dans l'onglet Préparateur."
        return
    real_id = upsert_real_intervention(current_id, {
        "work_done":      clean_text(st.session_state.real_work_done),
        "real_root_cause": clean_text(st.session_state.real_root_cause),
    })
    st.session_state._success_msg = f"✅ Retour terrain sauvegardé (#{real_id})"


def save_pre_intervention_callback() -> None:
    """Sauvegarde la pré-intervention courante et met à jour l'ID en session."""
    payload = build_payload()
    pre_id = save_pre_intervention(payload, st.session_state.current_pre_intervention_id)
    st.session_state.current_pre_intervention_id = pre_id
    st.session_state._success_msg = f"✅ Dossier sauvegardé (#{pre_id})"
