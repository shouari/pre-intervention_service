"""
ai_engine.py — Prompt IA et appel OpenAI.
"""
from __future__ import annotations

import json
import os
import textwrap
from typing import Any, Dict

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


def _get_openai_key() -> str:
    import streamlit as st
    key = (
        os.environ.get("OPENAI_API_KEY", "")
        or (st.secrets.get("OPENAI_API_KEY", "") if hasattr(st, "secrets") else "")
        or st.session_state.get("OPENAI_API_KEY", "")
    )
    return key.strip(" \"'")


def build_ai_prompt(payload: Dict[str, Any]) -> str:
    mandat    = payload.get("mandat", {})
    probleme  = payload.get("probleme", {})
    technique = payload.get("technique", {})

    service_call      = mandat.get("service_call", "") or ""
    intervention_goal = mandat.get("intervention_goal", "") or ""
    problem_desc      = probleme.get("reported_issue", "") or ""
    history_context   = technique.get("history_context", "") or ""

    systems = technique.get("systems_present", [])
    systems_str = "\n".join(f"- {s}" for s in systems) if systems else "Non spécifié"

    return textwrap.dedent(f"""
ROLE
Tu es un technicien senior en intégration audiovisuelle et réseau (résidentiel et commercial léger).
Tu dois préparer un appel de service pour un technicien terrain.

CONTEXTE

Type d'intervention: {service_call}
Objectif: {intervention_goal}

Problème rapporté:
{problem_desc}

Systèmes en place:
{systems_str}

Historique / contexte additionnel:
{history_context if history_context else "(aucun)"}

CONTRAINTE IMPORTANTE

* Tu n'as PAS accès au site
* Tu dois raisonner avec incertitude
* Évite toute supposition non réaliste

TÂCHE — Générer en JSON strict :

1. hypotheses (max 5) — classées par probabilité (high/medium/low), basées sur causes fréquentes terrain
2. action_plan — étapes concrètes et testables sur place, dans l'ordre
3. vigilance_points — erreurs fréquentes et risques
4. tools_required — matériel / logiciels nécessaires
5. sources — documentation fabricant ou standards (pas de liens inventés)

FORMAT DE RÉPONSE (JSON STRICT)

{{
  "hypotheses": [
    {{"description": "", "probability": "high|medium|low", "rationale": ""}}
  ],
  "action_plan": [
    {{"step": 1, "action": "", "expected_result": ""}}
  ],
  "vigilance_points": [],
  "tools_required": [],
  "sources": []
}}
""").strip()


def run_ai_analysis(payload: Dict[str, Any], doc_text: str = "") -> Dict[str, Any]:
    if not OPENAI_AVAILABLE:
        raise RuntimeError("Le package openai n'est pas installé (pip install openai).")

    key = _get_openai_key()
    if not key:
        raise RuntimeError("Clé API OpenAI introuvable. Ajoutez OPENAI_API_KEY dans .env ou st.secrets.")

    client = OpenAI(api_key=key)
    prompt = build_ai_prompt(payload)
    if doc_text:
        prompt += f"\n\nEXTRAITS DOCUMENTS DE TRAVAIL :\n{doc_text}"

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.3,
    )

    raw = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = {}

    # Aplatir la structure riche vers le format attendu par l'UI
    hypotheses = []
    for h in parsed.get("hypotheses", []):
        if isinstance(h, dict):
            prob_label = {"high": "🔴 Élevée", "medium": "🟡 Moyenne", "low": "🟢 Faible"}.get(
                h.get("probability", ""), h.get("probability", "")
            )
            hypotheses.append(f"[{prob_label}] {h.get('description', '')} — {h.get('rationale', '')}")
        else:
            hypotheses.append(str(h))

    action_plan = []
    for a in parsed.get("action_plan", []):
        if isinstance(a, dict):
            action_plan.append(f"Étape {a.get('step', '?')}: {a.get('action', '')} → {a.get('expected_result', '')}")
        else:
            action_plan.append(str(a))

    return {
        "summary":              "Analyse IA générée avec succès.",
        "hypotheses":           hypotheses,
        "priority_checks":      parsed.get("sources", []),
        "action_plan":          action_plan,
        "risks":                parsed.get("vigilance_points", []),
        "tools_or_access_needed": parsed.get("tools_required", []),
        "missing_information":  [],
        "confidence_level":     "Moyen",
        "raw_json":             raw,
    }
