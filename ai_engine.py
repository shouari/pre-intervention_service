"""
ai_engine.py — Prompt IA et appel OpenAI.
"""
from __future__ import annotations

import json
import os
import textwrap
from typing import Any, Dict, List

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

_SYSTEM_PROMPT = textwrap.dedent("""
Tu es un ingénieur senior en intégration AV, domotique et réseaux avec 15+ ans d'expérience terrain.
Tu travailles pour Groupe CS (Montréal, QC) — résidentiel haut-de-gamme et commercial léger.

COMPORTEMENT ATTENDU
Tu prépares un technicien expérimenté pour son intervention de demain.
Ce technicien SAIT déjà utiliser un tournevis, un multimètre et brancher des câbles.
Il n'a PAS besoin qu'on lui rappelle d'apporter des outils de base.
Ce dont il a besoin : savoir exactement quoi faire, dans quel ordre, sur quelle interface, avec quelle commande.

Conséquences directes :
- Concret avant tout : menu exact, commande CLI complète, chemin de fichier, firmware, référence de pièce
- La piste du technicien est évaluée EN PREMIER — elle prime sur toute analyse générale
- Si le tech pose une question explicite dans ses notes, RÉPONDS-Y directement et en priorité
- Si le tech suggère un remplacement, c'est une directive : elle figure dans le plan d'action
- Identifier ce qui manque vaut mieux qu'inventer des hypothèses creuses

DOMAINES MAÎTRISÉS

RÉSEAUX
- Unifi (UniFi OS, Network Application, USW, U6/U7, UDM-Pro, UXG) :
  SSH journaux, commandes `info` / `ubnt-systool`, /var/log/messages, adoption Wi-Fi,
  VLANs, port profiles, IDS/IPS, DPI, PoE cycling, firmware rolling updates
- Wattbox (WB-300/700/800-IPVM) : interface web locale (port 80), Wattbox Cloud,
  outlet status, scheduled reboots, circuit breaker blown vs outlet off

AUDIOVISUEL
- QSC (Q-SYS Designer, Core processors, UCI, DSP) :
  Status page, Component logs, peripheral discovery, UCI Designer
- Logitech (Rally Bar, Tap, Sync, MeetUp) :
  Sync portal, USB/IP modes, firmware rollback, Teams/Zoom Room mode

AUTOMATISATION
- Control4 (Composer Pro/HE, drivers, agents, variables, Lua) :
  Device connections, driver version pinning, binding issues, project backup/restore
  Chemins migration : HC-300 / HC-800 → EA-1 / EA-3 / CA-10 (export projet, re-import, re-binding)
- Crestron (XPanel, SIMPL Windows, Toolbox, VC-4) :
  IP table, SIMPL debugger, program slots, ERR logs
- Lutron (Caseta, RA3, HomeWorks QS/QSX, Inclusive) :
  Calibration stores motorisés via app Lutron (jamais multimètre), DB backup AVANT tout changement,
  protocoles QS/LEAP, RadioRA 3 app

SURVEILLANCE & ACCÈS
- Hikvision / Luma / Clare : SADP, TFTP firmware, NVR reset, droits d'accès
- Unifi Protect : UNVR/UCK, retention, stream quality, camera adoption
- Salto : PPD Salto (codes erreur LED), remplacement batterie, synchronisation accès
- Unifi Access / CDVI / Paradox / DSC : credential sync, access levels, zone arming, expansion cards

RÈGLES ABSOLUES
- Réponds en français dans tous les champs texte
- Nomme les menus exacts, chemins, commandes — jamais de vague
- Ne suggère JAMAIS une action déjà dans les tentatives précédentes
- N'invente aucune URL, lien ou référence non vérifiable
- Si plusieurs systèmes sont en jeu, évalue les points d'intégration
- Le champ "tools_and_access" ne contient JAMAIS : tournevis, multimètre, câble HDMI/Ethernet,
  testeur de câbles, ou tout autre outil physique qu'un technicien a toujours dans son sac.
  Ce champ contient UNIQUEMENT : logiciel + version, accès/credentials, références de pièces
  à commander ou apporter, documents spécifiques à télécharger avant l'intervention.
""").strip()


# ─── Formatage de l'historique interne ────────────────────

def _format_similar_cases(cases: List[Dict[str, Any]]) -> str:
    lines = [
        "### CAS SIMILAIRES RÉSOLUS — BASE INTERNE GROUPE CS",
        "Ces interventions passées partagent les mêmes systèmes. "
        "Les résolutions confirmées ont la priorité sur les hypothèses génériques.",
    ]
    for c in cases:
        try:
            p = json.loads(c["payload_json"])
            prob = p.get("probleme", {}).get("reported_issue", "—")[:150]
            goal = p.get("mandat", {}).get("intervention_goal", "")[:100]
            systems = json.loads(c.get("systems_present_json") or "[]")
            work = (c.get("work_done") or "").strip()[:350]
            root = (c.get("real_root_cause") or "").strip()
            rec  = (c.get("rec_notes") or "").strip()
            missing = (c.get("missing_critical_info") or "").strip()

            lines.append(f"\n[Cas #{c['id']} — {c['client_name']} | {', '.join(systems)}]")
            if goal:
                lines.append(f"Objectif : {goal}")
            lines.append(f"Problème : {prob}")
            if work:
                lines.append(f"Ce qui a été fait : {work}")
            if root:
                lines.append(f"Cause racine confirmée : {root}")
            if rec:
                lines.append(f"Note retour : {rec}")
            if missing:
                lines.append(f"Info qui aurait aidé : {missing}")
        except Exception:
            continue
    return "\n".join(lines)


# ─── Construction du message utilisateur ──────────────────

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
        section("ANALYSE PRÉLIMINAIRE DU TECHNICIEN — LIRE EN PREMIER", history_context),
        section("DÉJÀ ESSAYÉ — NE PAS RE-SUGGÉRER", attempts),
        section("CONTRAINTES SUR PLACE", site_constraints),
        section("RÉFÉRENCES / ACCÈS DISPONIBLES", references),
        "",
        textwrap.dedent("""
        # TÂCHE

        Analyse ce cas pour préparer le technicien. Commence par raisonner librement
        dans "raisonnement", puis remplis les autres champs.
        Réponds UNIQUEMENT avec le JSON ci-dessous — aucun texte avant ou après.

        ```json
        {
          "raisonnement": "Raisonnement étape par étape AVANT les conclusions. Min. 150 mots. Couvre obligatoirement : (1) type d'intervention — diagnostic, remplacement ciblé, configuration logicielle, installation, ou survey ; (2) questions explicites posées par le technicien dans ses notes et tes réponses directes ; (3) ce qu'on sait avec certitude vs ce qui est ambigu ; (4) pourquoi la piste du technicien est crédible ou non ; (5) cause racine la plus probable.",

          "technical_assessment": "2-3 phrases : type d'intervention, cause racine la plus probable, réponse directe aux questions du technicien si applicable.",

          "hypotheses": [
            {
              "cause": "Cause précise — si formulée par le technicien, reprends mot pour mot et évalue",
              "probability": "high | medium | low",
              "system": "Composant exact (ex: WB-700-IPVM outlet #3, USW-48 port 12, HC-300 firmware OS2.5.3)",
              "evidence": "Indices concrets dans les symptômes ou l'historique",
              "verification": "Procédure exacte : interface, menu, commande, log — pas de vague"
            }
          ],

          "priority_checks": [
            "Étape #1 avec procédure exacte — ex: SSH udm-pro → cat /var/log/messages | grep 'eth' | tail -50",
            "Étape #2...",
            "Omis si intervention de type remplacement ciblé ou configuration pure — mettre [] dans ce cas"
          ],

          "action_plan": [
            {
              "action": "Action spécifique — les remplacements et étapes mentionnés par le tech figurent ici en priorité",
              "method": "Procédure exacte : menu, commande CLI, chemin de fichier, référence de pièce",
              "expected_result": "Ce qu'on observe si l'action réussit"
            }
          ],

          "tools_and_access": [
            "Logiciel requis : [nom exact + version minimale si pertinente]",
            "Accès/credentials : [portail, SSH, login spécifique à ce client]",
            "Pièce à commander ou apporter : [référence exacte, modèle précis]",
            "Document : [guide de migration, changelog firmware, backup à faire avant]"
          ],

          "known_issues": [
            "Bogue firmware documenté, limitation plateforme ou comportement connu lié à ce cas"
          ],

          "warnings": [
            "Risque critique : perte de données, coupure de service, action irréversible"
          ],

          "missing_info": [
            "Information précise qui changerait l'analyse si connue"
          ]
        }
        ```

        Règles non-négociables :
        - "raisonnement" est le premier champ — le remplir sérieusement conditionne tout le reste
        - Si le technicien pose une question dans ses notes, la réponse est dans "raisonnement" ET "technical_assessment"
        - L'hypothèse du technicien est la première entrée de "hypotheses" avec évaluation explicite
        - Tout remplacement ou action mentionné par le technicien figure dans "action_plan"
        - "tools_and_access" = logiciels, accès, pièces, documents — JAMAIS tournevis / multimètre / câbles
        - Maximum 5 hypothèses, de la plus probable à la moins probable
        - Plan d'action séquentiel : chaque étape peut dépendre de la précédente
        - Tous les champs texte en français
        """).strip(),
    ]

    return "\n\n".join(b for b in blocks if b.strip())


# ─── Recherche web ciblée ──────────────────────────────────

def _run_web_research(client: OpenAI, systems: list, problem_desc: str, history_context: str) -> str:
    """
    gpt-4o-search-preview: KB fabricant, changelogs firmware, forums communautaires.
    Dégradation silencieuse — l'analyse principale se fait même si indisponible.
    """
    systems_str = ", ".join(systems) if systems else "Non précisé"
    query = textwrap.dedent(f"""
        Recherche d'informations techniques pour un dépannage d'intégration AV/réseau.

        Équipements concernés : {systems_str}
        Problème rapporté : {problem_desc}
        Notes du technicien : {history_context}

        Cherche :
        1. Articles KB ou guides de dépannage fabricant correspondant à ces symptômes
        2. Bogues firmware connus ou notes de version récentes pour les modèles mentionnés
        3. Fils de forum communautaire (Ubiquiti Community, Control4 forums, AVS Forum, Reddit r/homelab, r/UNIFI) avec cas similaires résolus
        4. Procédures de migration ou de remplacement documentées

        Sois concis — uniquement ce qui est directement actionnable.
        Cite brièvement la source pour chaque point. Réponds en français.
    """).strip()

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-search-preview",
            web_search_options={},
            messages=[{"role": "user", "content": query}],
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception:
        return ""


# ─── Appel API ─────────────────────────────────────────────

def run_ai_analysis(payload: Dict[str, Any], doc_text: str = "") -> Dict[str, Any]:
    if not OPENAI_AVAILABLE:
        raise RuntimeError("Le package openai n'est pas installé (pip install openai).")

    key = _get_openai_key()
    if not key:
        raise RuntimeError("Clé API OpenAI introuvable. Ajoutez OPENAI_API_KEY dans .env ou st.secrets.")

    client = OpenAI(api_key=key)

    technique    = payload.get("technique", {})
    probleme     = payload.get("probleme", {})
    systems      = technique.get("systems_present") or []
    problem_desc = (probleme.get("reported_issue") or "").strip()
    history_ctx  = (technique.get("history_context") or "").strip()

    # ── Étape 1 : recherche web ────────────────────────────────
    web_research = _run_web_research(client, systems, problem_desc, history_ctx)

    # ── Étape 1b : historique interne ─────────────────────────
    from database import get_similar_cases
    similar_cases = get_similar_cases(systems, limit=4)

    # ── Étape 2 : analyse structurée JSON ─────────────────────
    user_prompt = build_ai_prompt(payload)

    if similar_cases:
        user_prompt += "\n\n" + _format_similar_cases(similar_cases)

    if web_research:
        user_prompt += f"\n\n### RECHERCHE EN LIGNE — RÉSULTATS ACTUELS (fabricant, forums, KB)\n{web_research}"

    if doc_text:
        user_prompt += textwrap.dedent(f"""

        ### DOCUMENTS DE TRAVAIL (extraits)
        Ces fichiers peuvent inclure : projets Control4 (XML — liste des appareils, drivers, versions, bindings),
        backups Crestron (SIMPL+/USP — logique de programmation, IP table), fichiers Q-SYS (.qsys),
        configurations Lutron (.lut), logs système, ou tout autre document technique.

        Extrais et utilise activement :
        - Versions exactes des drivers et firmware mentionnées
        - Liste des appareils et leurs connexions
        - Configurations réseau (IP, VLAN, ports)
        - Erreurs ou avertissements dans les logs
        - Tout élément directement pertinent pour le problème décrit

        {doc_text}
        """).strip()

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.45,
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
            line += f"\n  Indices : {evid}"
        if verif:
            line += f"\n  Vérifier : {verif}"
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

    # ── Risques = warnings + known issues ─────────────────────
    risks = (
        [str(w) for w in parsed.get("warnings", [])]
        + [str(k) for k in parsed.get("known_issues", [])]
    )

    return {
        "summary":                parsed.get("technical_assessment", "Analyse IA générée."),
        "raisonnement":           parsed.get("raisonnement", ""),
        "web_research":           web_research,
        "hypotheses":             hypotheses,
        "priority_checks":        [str(c) for c in parsed.get("priority_checks", [])],
        "action_plan":            action_plan,
        "risks":                  risks,
        "tools_or_access_needed": [str(t) for t in parsed.get("tools_and_access", [])],
        "missing_information":    [str(m) for m in parsed.get("missing_info", [])],
        "raw_json":               raw,
    }
