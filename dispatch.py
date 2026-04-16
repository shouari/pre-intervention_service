"""
dispatch.py — Génération des emails de dispatch et envoi via Brevo API.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import requests

from config import TECH_EMAIL_MAP
from database import get_dispatch_for_day, log_dispatch
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


# ─── Construction du texte email ───────────────────────────

def build_dispatch_email(tech: str, calls: List[Dict[str, Any]], date_str: str) -> str:
    readable_date = format_french_date(date_str)
    first_name = tech.split()[0] if tech else "Technicien"

    lines = [
        f"Bonjour {first_name},",
        "",
        f"Voici tes appels de service pour le {readable_date} :",
        "",
    ]

    for i, call in enumerate(calls, 1):
        dt = call.get("scheduled_datetime", "") or ""
        time_str = dt[11:16] if len(dt) >= 16 else "??"
        client  = call.get("client_name") or "Client inconnu"
        address = call.get("address")    or "Adresse non précisée"
        goal    = call.get("intervention_goal") or "Non précisé"
        lines += [
            f"{i}. {time_str} — {client}",
            f"   📍 {address}",
            f"   🎯 {goal}",
            "",
        ]

    lines += ["Les fiches PDF sont aussi disponibles dans D-Tools", "", "Bonne journée."]
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
            import re
            emails = [e.strip() for e in re.split(r"[,;]+", cc_email_str) if e.strip()]
            for e in emails:
                cc_list.append({"email": e})

        email_text = build_dispatch_email(tech, calls, date_str)

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
                    client = safe_filename(call.get("client_name", "client"))
                    sc     = safe_filename(call.get("service_call", "app"))
                    fname  = f"interv_{client}_{sc}.pdf" if sc else f"interv_{client}.pdf"
                    attachments.append({"name": fname, "content": b64})

        req_body: Dict[str, Any] = {
            "sender":      {"name": "Dispatch Service", "email": sender_email},
            "to":          [{"email": tech_email_str, "name": tech}],
            "subject":     f"Appels de service - {format_french_date(date_str)}",
            "textContent": email_text,
        }
        if cc_list:
            req_body["cc"] = cc_list
        if attachments:
            req_body["attachment"] = attachments

        try:
            resp = requests.post(url, headers=headers, json=req_body, timeout=15)
            if resp.status_code in (200, 201, 202):
                results.append({"tech": tech, "status": "success", "message": "Email envoyé avec succès."})
                log_dispatch(tech, date_str, "Success")
            else:
                msg = f"Erreur API ({resp.status_code}): {resp.text}"
                results.append({"tech": tech, "status": "error", "message": msg})
                log_dispatch(tech, date_str, "Error", resp.text)
        except Exception as e:
            msg = f"Exception locale : {e}"
            results.append({"tech": tech, "status": "error", "message": msg})
            log_dispatch(tech, date_str, "Exception", str(e))

    return results
