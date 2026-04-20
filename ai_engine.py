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


# ─── Persona système ───────────────────────────────────────
# Séparé du cas client : rôle, comportement, profondeur technique.

_SYSTEM_PROMPT = textwrap.dedent("""
Tu es un ingénieur senior en intégration AV, domotique et réseaux avec 15+ ans d'expérience terrain.
Tu travailles pour Groupe CS (Montréal, QC) — intégration résidentielle et commerciale légère.

Tes connaissances couvrent en profondeur :

RÉSEAUX
- Unifi (UniFi OS, Network Application, switches USW, APs U6/U7, UDM-Pro, UXG) :
  journaux SSH, commandes `info`, `ubnt-systool`, fichiers /var/log, adoption Wi-Fi,
  VLANs, profiles, IDS/IPS, DPI, port profiles, PoE cycling, firmware rolling updates

AUDIOVISUEL
- QSC (Q-SYS Designer, Core processors, UCI, audio routing, DSP) :
  Q-SYS Designer diagnostics, Status page, Component logs, peripheral discovery
- Logitech (Rally Bar, Tap, Sync, MeetUp) :
  Sync portal, USB/IP modes, firmware rollback, Teams/Zoom Room mode issues

AUTOMATISATION
- Control4 (Composer Pro / HE, drivers, agents, variables, programming) :
  Device connections, Lua debugging, driver versions, binding issues, project backup/restore
- Crestron (XPanel, SIMPL Windows, Toolbox, VC-4) :
  Toolbox diagnostics, IP table, SIMPL debugger, program slots, ERR logs
- Lutron (Caseta, RA3, HomeWorks QS/QSX, Inclusive) :
  Lutron Designer / Inclusive software, DB backup avant tout changement,
  calibration stores motorisés, groupes et scènes, protocoles QS/LEAP

SURVEILLANCE & ACCÈS
- Hikvision / Luma : SADP, ports, firmware via TFTP, réinitialisation NVR, droits d'accès
- Unifi Protect : Consoles UNVR/UCK, retention, stream quality, camera adoption
- Unifi Access / CDVI / Paradox / DSC : credential sync, door access levels, zone arming

PRINCIPES DE DIAGNOSTIC
- Toujours isoler : matériel → firmware → configuration → intégration
- Les problèmes multi-systèmes ont souvent une seule cause racine (réseau, alimentation, timing)
- Vérifier les journaux avant de toucher à la configuration
- Ne jamais modifier sans sauvegarder (Lutron DB, Control4 project, Crestron program)

RÈGLES ABSOLUES
- Réponds en français dans tous les champs texte
- Sois précis : nomme les menus exacts, chemins, commandes CLI, numéros de firmware si pertinents
- Ne suggère JAMAIS une action déjà mentionnée dans les tentatives précédentes
- N'invente aucune URL, aucun lien, aucune référence non vérifiable
- Si plusieurs systèmes sont en jeu, évalue les points d'intégration (drivers, IP, protocoles)
""").strip()


# ─── Construction du message utilisateur ──────────────────
# Aucune donnée personnelle (nom, adresse, téléphone).

def build_ai_prompt(payload: Dict[str, Any]) -> str:
    mandat    = payload.get("mandat", {})
    probleme  = payload.get("probleme", {})
    technique = payload.get("technique", {})

    service_call      = (mandat.get("service_call")      or "").strip()
    intervention_goal = (mandat.get("intervention_goal") or "").strip()
    problem_desc      = (probleme.get("reported_issue")  or "").strip()
    history_context   = (technique.get("history_context")    or "").strip()
    attempts          = (technique.get("attempts_summary")   or "").strip()
    site_constraints  = (technique.get("site_constraints")   or "").strip()
    references        = (technique.get("references_utiles")  or "").strip()

    systems = technique.get("systems_present") or []
    systems_str = ", ".join(systems) if systems else "Non précisé"

    def section(title: str, content: str) -> str:
        return f"### {title}\n{content}" if content.strip() else ""

    blocks = [
        f"# APPEL DE SERVICE{' #' + service_call if service_call else ''}",
        "",
        section("OBJECTIF", intervention_goal),
        section("PROBLÈME RAPPORTÉ", problem_desc),
        f"### SYSTÈMES EN PLACE\n{systems_str}",
        section("HISTORIQUE / CONTEXTE TECHNIQUE", history_context),
        section("DÉJÀ ESSAYÉ — NE PAS RE-SUGGÉRER", attempts),
        section("CONTRAINTES SUR PLACE", site_constraints),
        section("RÉFÉRENCES / ACCÈS DISPONIBLES", references),
        "",
        textwrap.dedent("""
        # TÂCHE

        Analyse ce cas en expert. Utilise ta connaissance approfondie des systèmes listés
        (manuels, comportements firmware, bogues connus, logs, commandes CLI, chemins de menus exacts).

        Réponds uniquement avec le JSON ci-dessous — aucun texte avant ou après.

        ```json
        {
          "technical_assessment": "Synthèse technique : analyse globale du problème, systèmes impliqués, cause racine la plus probable",

          "hypotheses": [
            {
              "cause": "Cause technique précise",
              "probability": "high | medium | low",
              "system": "Système ou composant concerné",
              "evidence": "Indices dans les symptômes qui pointent vers cette cause",
              "verification": "Test ou observation exact qui confirme/infirme — préciser menu, commande ou log"
            }
          ],

          "priority_checks": [
            "Vérification #1 avec méthode précise — ex: UniFi Controller > Devices > [switch] > Logs, chercher 'PoE overload'",
            "Vérification #2 ...",
            "..."
          ],

          "action_plan": [
            {
              "action": "Action spécifique",
              "method": "Procédure exacte : chemin de menu, commande CLI, paramètre à modifier",
              "expected_result": "Ce qu'on observe si l'action réussit"
            }
          ],

          "tools_and_access": [
            "Outil, logiciel (avec version si pertinente), câble ou accès nécessaire"
          ],

          "known_issues": [
            "Bogue firmware connu, limitation plateforme ou comportement documenté lié à ce cas"
          ],

          "warnings": [
            "Avertissement critique : risque de perte de données, coupure de service, ou action irréversible"
          ],

          "missing_info": [
            "Information technique absente qui changerait significativement l'analyse"
          ]
        }
        ```

        Contraintes :
        - Maximum 5 hypothèses, de la plus probable à la moins probable
        - Minimum 3 vérifications prioritaires, ordonnées par rapport coût/valeur diagnostique
        - Le plan d'action doit être séquentiel — chaque étape peut dépendre de la précédente
        - Tous les champs texte en français
        """).strip(),
    ]

    return "\n\n".join(b for b in blocks if b.strip())


# ─── Appel API ─────────────────────────────────────────────

def run_ai_analysis(payload: Dict[str, Any], doc_text: str = "") -> Dict[str, Any]:
    if not OPENAI_AVAILABLE:
        raise RuntimeError("Le package openai n'est pas installé (pip install openai).")

    key = _get_openai_key()
    if not key:
        raise RuntimeError("Clé API OpenAI introuvable. Ajoutez OPENAI_API_KEY dans .env ou st.secrets.")

    client = OpenAI(api_key=key)
    user_prompt = build_ai_prompt(payload)
    if doc_text:
        user_prompt += f"\n\n### DOCUMENTS DE TRAVAIL (extraits)\n{doc_text}"

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.25,
    )

    raw = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = {}

    # ── Hypothèses ────────────────────────────────────────────
    prob_labels = {"high": "Élevée", "medium": "Moyenne", "low": "Faible"}
    hypotheses = []
    for h in parsed.get("hypotheses", []):
        if not isinstance(h, dict):
            hypotheses.append(str(h))
            continue
        prob  = prob_labels.get(h.get("probability", ""), h.get("probability", ""))
        cause = h.get("cause", "")
        sys_  = h.get("system", "")
        evid  = h.get("evidence", "")
        verif = h.get("verification", "")
        line  = f"[{prob}]" + (f" {sys_} —" if sys_ else "") + f" {cause}"
        if evid:
            line += f"\n  → Indices : {evid}"
        if verif:
            line += f"\n  → Vérifier : {verif}"
        hypotheses.append(line)

    # ── Plan d'action ─────────────────────────────────────────
    action_plan = []
    for a in parsed.get("action_plan", []):
        if not isinstance(a, dict):
            action_plan.append(str(a))
            continue
        action = a.get("action", "")
        method = a.get("method", "")
        result = a.get("expected_result", "")
        line = action
        if method:
            line += f"\n  Procédure : {method}"
        if result:
            line += f"\n  Résultat attendu : {result}"
        action_plan.append(line)

    # ── Risques = warnings prioritaires + known issues ────────
    risks = (
        [str(w) for w in parsed.get("warnings", [])]
        + [str(k) for k in parsed.get("known_issues", [])]
    )

    return {
        "summary":               parsed.get("technical_assessment", "Analyse IA générée."),
        "hypotheses":            hypotheses,
        "priority_checks":       [str(c) for c in parsed.get("priority_checks", [])],
        "action_plan":           action_plan,
        "risks":                 risks,
        "tools_or_access_needed":[str(t) for t in parsed.get("tools_and_access", [])],
        "missing_information":   [str(m) for m in parsed.get("missing_info", [])],
        "confidence_level":      "Moyen",
        "raw_json":              raw,
    }
