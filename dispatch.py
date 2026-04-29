"""
dispatch.py — Génération des emails de dispatch et envoi via Brevo API.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

import requests

from config import TECH_EMAIL_MAP, APP_VERSION
from database import log_dispatch, get_last_dispatch_snapshot, get_dispatch_send_count
from pdf_engine import encode_pdf_base64
from utils import format_french_date, safe_filename


def _get_brevo_key() -> str:
    import streamlit as st
    key = (
        os.environ.get("BREVO_API_KEY", "")
        or (st.secrets.get("BREVO_API_KEY", "") if hasattr(st, "secrets") else "")
    )
    return key.strip(" \"'")


def _get_sender_email() -> str:
    return os.environ.get("BREVO_SENDER_EMAIL", "").strip(" \"'") or "no-reply@votredomaine.com"


# ─── Helpers détection de mise à jour ──────────────────────

def _build_snapshot(calls: List[Dict[str, Any]]) -> Dict[str, Any]:
    summary = [
        {
            "id":           c.get("id"),
            "updated_at":   c.get("updated_at", ""),
            "client_name":  c.get("client_name", ""),
            "service_call": c.get("service_call", ""),
        }
        for c in calls
    ]
    return {"call_ids": [c["id"] for c in summary], "calls_summary": summary}


def _compute_changes(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, List]:
    old_by_id = {c["id"]: c for c in old.get("calls_summary", [])}
    new_by_id = {c["id"]: c for c in new.get("calls_summary", [])}
    added    = [c for id_, c in new_by_id.items() if id_ not in old_by_id]
    removed  = [c for id_, c in old_by_id.items() if id_ not in new_by_id]
    modified = [
        new_by_id[id_] for id_ in new_by_id
        if id_ in old_by_id and new_by_id[id_]["updated_at"] != old_by_id[id_]["updated_at"]
    ]
    return {"added": added, "removed": removed, "modified": modified}


def _format_changes(changes: Dict[str, List]) -> str:
    def _label(c: Dict) -> str:
        name = c.get("client_name", "—")
        sc   = c.get("service_call", "")
        return f"{name} ({sc})" if sc else name

    parts = []
    if changes["added"]:
        parts.append(f"{len(changes['added'])} ajout{'s' if len(changes['added']) > 1 else ''}: " +
                     ", ".join(_label(c) for c in changes["added"]))
    if changes["removed"]:
        parts.append(f"{len(changes['removed'])} suppression{'s' if len(changes['removed']) > 1 else ''}: " +
                     ", ".join(_label(c) for c in changes["removed"]))
    if changes["modified"]:
        parts.append(f"{len(changes['modified'])} modification{'s' if len(changes['modified']) > 1 else ''}: " +
                     ", ".join(_label(c) for c in changes["modified"]))
    return " · ".join(parts) if parts else "Contenu inchangé"


# ─── Construction du texte email ───────────────────────────

def build_dispatch_email(tech: str, calls: List[Dict[str, Any]], date_str: str) -> str:
    # On garde la version texte pour le fallback ou les logs
    readable_date = format_french_date(date_str)
    first_name = tech.split()[0] if tech else "Technicien"
    lines = [f"Bonjour {first_name},", "", f"Voici tes appels de service pour le {readable_date} :", ""]
    for call in calls:
        dt = call.get("scheduled_datetime", "") or ""
        time_str = dt[11:16] if len(dt) >= 16 else "??"
        client  = call.get("client_name") or "Client inconnu"
        address = call.get("address")    or "Adresse non précisée"
        goal    = call.get("intervention_goal") or "Non précisé"
        lines += [f"🕒 {time_str} — {client}", f"   📍 {address}", f"   🎯 {goal}", ""]
    lines += ["Les fiches PDF sont aussi disponibles dans D-Tools.", "Bonne journée."]
    return "\n".join(lines)


# ─── Envoi via Brevo ────────────────────────────────────────

def send_dispatch_emails(
    grouped_dispatch: Dict[str, List[Dict[str, Any]]],
    date_str: str,
    tech_emails: Optional[Dict[str, str]] = None,
    tech_emails_cc: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:

    brevo_key = _get_brevo_key()
    if not brevo_key:
        return [{"tech": "Système", "status": "error",
                 "message": "Clé API Brevo (BREVO_API_KEY) absente. Impossible d'envoyer."}]

    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "api-key":      brevo_key,
        "content-type": "application/json",
        "accept":       "application/json",
    }
    sender_email = _get_sender_email()
    results: List[Dict[str, Any]] = []

    for tech, calls in grouped_dispatch.items():
        # Détecter s'il s'agit d'une mise à jour
        prev_snapshot  = get_last_dispatch_snapshot(tech, date_str)
        new_snapshot   = _build_snapshot(calls)
        send_count     = get_dispatch_send_count(tech, date_str)
        is_update      = send_count > 0

        if is_update and prev_snapshot:
            changes             = _compute_changes(prev_snapshot, new_snapshot)
            changes_description = _format_changes(changes)
        elif is_update:
            changes_description = "Détail des modifications non disponible pour cet envoi."
        else:
            changes_description = ""

        # Résoudre l'email destinataire
        tech_email_str = (tech_emails or {}).get(tech) or TECH_EMAIL_MAP.get(tech)
        
        if not tech_email_str or not tech_email_str.strip():
            msg = "Aucun courriel spécifié."
            results.append({"tech": tech, "status": "skipped", "message": msg})
            log_dispatch(tech, date_str, "Skipped", msg)
            continue
            
        tech_email_str = tech_email_str.strip()

        # Handle CC
        cc_email_str = (tech_emails_cc or {}).get(tech)
        cc_list = []
        if cc_email_str and cc_email_str.strip():
            emails = [e.strip() for e in re.split(r"[,;]+", cc_email_str) if e.strip()]
            for e in emails:
                cc_list.append({"email": e})

        # Construire la liste d'appels pour les templates qui itèrent
        calls_data = []
        for c in calls:
            dt = c.get("scheduled_datetime", "") or ""
            calls_data.append({
                "time_str":          dt[11:16] if len(dt) >= 16 else "??",
                "client_name":       c.get("client_name") or "Client",
                "address":           c.get("address") or "",
                "intervention_goal": c.get("intervention_goal") or "",
            })

        # Construire les pièces jointes PDF
        attachments = []
        for call in calls:
            try:
                payload = json.loads(call.get("payload_json") or "{}")
            except Exception:
                payload = None
            if payload:
                b64 = encode_pdf_base64(payload)
                if b64:
                    client_fname = safe_filename(call.get("client_name", "client"))
                    sc_fname     = safe_filename(call.get("service_call", "app"))
                    fname  = f"interv_{client_fname}_{sc_fname}.pdf" if sc_fname else f"interv_{client_fname}.pdf"
                    attachments.append({"name": fname, "content": b64})

        first_name  = tech.split()[0] if tech else "Technicien"
        readable_dt = format_french_date(date_str)
        req_body: Dict[str, Any] = {
            "templateId":  10,
            "sender":      {"name": "Planification Intervention", "email": sender_email},
            "to":          [{"email": tech_email_str, "name": tech}],
            "params": {
                "first_name":           first_name,
                "readable_date":        readable_dt,
                "call_count":           len(calls),
                "calls":                calls_data,
                "is_update":            is_update,
                "send_number":          send_count + 1,
                "changes_description":  changes_description,
                "app_version":          APP_VERSION,
            },
        }
        if is_update:
            req_body["subject"] = f"🔄 Mise à jour #{send_count + 1} — Appels de service du {readable_dt}"
        if cc_list:
            req_body["cc"] = cc_list
        if attachments:
            req_body["attachment"] = attachments

        try:
            resp = requests.post(url, headers=headers, json=req_body, timeout=15)
            if resp.status_code in (200, 201, 202):
                results.append({"tech": tech, "status": "success", "message": "Email envoyé avec succès."})
                log_dispatch(tech, date_str, "Success", json.dumps(new_snapshot, ensure_ascii=False))
            else:
                msg = f"Erreur API ({resp.status_code}): {resp.text}"
                results.append({"tech": tech, "status": "error", "message": msg})
                log_dispatch(tech, date_str, "Error", resp.text)
        except Exception as e:
            msg = f"Exception locale : {e}"
            results.append({"tech": tech, "status": "error", "message": msg})
            log_dispatch(tech, date_str, "Exception", str(e))

    return results
