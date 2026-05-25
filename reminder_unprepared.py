"""
reminder_unprepared.py — Rappel email pour les appels de service non préparés.

Usage (planifier via Windows Task Scheduler) :
    python reminder_unprepared.py              → vérifie pour DEMAIN
    python reminder_unprepared.py 2026-05-27   → vérifie pour la date spécifiée

Critères "non préparé" (un seul suffit) :
    1. completion_score < 70
    2. intervention_goal vide ou null (plan d'action = champ intervention_goal)
    3. assigned_technician vide ou null

Envoie UN email consolidé à service@groupecs.com si au moins 1 SC non préparé.
Ne renvoie PAS si un rappel a déjà été envoyé pour cette date aujourd'hui
(vérification via dispatch_log, status="Reminder").

Variables d'environnement requises (ou dans .env) :
    BREVO_API_KEY        clé API Brevo
    BREVO_SENDER_EMAIL   adresse expéditeur
"""
from __future__ import annotations

import json
import os
import sys
import logging
import requests
from datetime import date, timedelta
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

from database import init_db, get_conn, log_dispatch
from utils import format_french_date, format_datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            Path(__file__).resolve().parent / "data" / "reminder.log",
            encoding="utf-8",
        ),
    ],
)
log = logging.getLogger(__name__)


# ── Critères de non-préparation ───────────────────────────

def get_unprepared_calls(date_str: str) -> list[dict]:
    """
    Retourne les SC planifiés pour date_str qui ne sont pas prêts.
    Critères (un seul suffit) :
      - completion_score < 70
      - intervention_goal vide ou null
      - assigned_technician vide ou null
    """
    conn = get_conn()
    rows = conn.execute("""
        SELECT id, client_name, scheduled_datetime, service_call,
               assigned_technician, intervention_goal, completion_score, address
        FROM pre_interventions
        WHERE scheduled_datetime LIKE ? || '%'
        AND (
            completion_score < 70
            OR intervention_goal IS NULL OR TRIM(intervention_goal) = ''
            OR assigned_technician IS NULL OR TRIM(assigned_technician) = ''
        )
        ORDER BY scheduled_datetime ASC
    """, (date_str,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Vérification : rappel déjà envoyé aujourd'hui ? ──────

def reminder_already_sent(date_str: str) -> bool:
    """
    Retourne True si un rappel a déjà été envoyé aujourd'hui pour cette date cible.
    Utilise dispatch_log avec technician="__reminder__" et status="Reminder".
    """
    from datetime import datetime as _dt
    today = _dt.now().strftime("%Y-%m-%d")
    conn = get_conn()
    row = conn.execute("""
        SELECT COUNT(*) AS cnt FROM dispatch_log
        WHERE technician = '__reminder__'
        AND dispatch_date = ?
        AND status = 'Reminder'
        AND timestamp LIKE ? || '%'
    """, (date_str, today)).fetchone()
    conn.close()
    return int(row["cnt"]) > 0


def log_reminder_sent(date_str: str, details: str = "") -> None:
    """Log l'envoi du rappel dans dispatch_log."""
    log_dispatch("__reminder__", date_str, "Reminder", details)


# ── Envoi via Brevo ───────────────────────────────────────

def send_reminder_email(date_str: str, unprepared: list[dict]) -> bool:
    """
    Envoie l'email de rappel consolidé via Brevo templateId=11.
    Retourne True si succès.

    Params Brevo :
      readable_date   : str  — ex: "26 mai 2026"
      call_count      : int  — nombre de SC non préparés
      calls           : list[dict] avec clés :
                          time_str, client_name, address,
                          technician, service_call,
                          completion_score, missing_fields
    """
    brevo_key = os.environ.get("BREVO_API_KEY", "").strip(" \"'")
    if not brevo_key:
        log.error("BREVO_API_KEY absente.")
        return False

    sender_email = os.environ.get("BREVO_SENDER_EMAIL", "").strip(" \"'") \
                   or "no-reply@groupecs.com"

    calls_data = []
    for c in unprepared:
        dt       = c.get("scheduled_datetime") or ""
        time_str = dt[11:16] if len(dt) >= 16 else "??"

        missing = []
        if (c.get("completion_score") or 0) < 70:
            missing.append(f"complétion {c.get('completion_score', 0)}%")
        if not (c.get("intervention_goal") or "").strip():
            missing.append("objectif vide")
        if not (c.get("assigned_technician") or "").strip():
            missing.append("technicien non assigné")

        calls_data.append({
            "time_str":        time_str,
            "client_name":     c.get("client_name") or "—",
            "address":         c.get("address") or "—",
            "technician":      c.get("assigned_technician") or "Non assigné",
            "service_call":    c.get("service_call") or "—",
            "completion_score": c.get("completion_score") or 0,
            "missing_fields":  " · ".join(missing),
        })

    req_body = {
        "templateId": 11,
        "sender":     {"name": "Système SAV", "email": sender_email},
        "to":         [{"email": "service@groupecs.com", "name": "Service Groupe CS"}],
        "params": {
            "readable_date": format_french_date(date_str),
            "call_count":    len(unprepared),
            "calls":         calls_data,
        },
    }

    try:
        resp = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={
                "api-key":      brevo_key,
                "content-type": "application/json",
                "accept":       "application/json",
            },
            json=req_body,
            timeout=15,
        )
        if resp.status_code in (200, 201, 202):
            return True
        log.error("Brevo erreur %s : %s", resp.status_code, resp.text[:200])
        return False
    except Exception as exc:
        log.error("Exception Brevo : %s", exc)
        return False


# ── Entrypoint ────────────────────────────────────────────

def run(target_date: date) -> None:
    date_str = target_date.strftime("%Y-%m-%d")
    readable = format_french_date(date_str)
    log.info("=== Rappel appels non préparés pour le %s ===", readable)

    init_db()

    if reminder_already_sent(date_str):
        log.info("Rappel déjà envoyé aujourd'hui pour le %s — ignoré.", readable)
        return

    unprepared = get_unprepared_calls(date_str)

    if not unprepared:
        log.info("Tous les appels du %s sont préparés — aucun rappel nécessaire.", readable)
        return

    log.info("%d appel(s) non préparé(s) pour le %s :", len(unprepared), readable)
    for c in unprepared:
        log.info("  · %s — %s (score: %s%%)",
                 c.get("service_call"), c.get("client_name"), c.get("completion_score"))

    success = send_reminder_email(date_str, unprepared)

    if success:
        log.info("Email de rappel envoyé à service@groupecs.com.")
        log_reminder_sent(date_str, json.dumps(
            {"count": len(unprepared),
             "calls": [c.get("service_call") for c in unprepared]},
            ensure_ascii=False,
        ))
    else:
        log.error("Échec de l'envoi du rappel.")


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        try:
            target = date.fromisoformat(sys.argv[1])
        except ValueError:
            log.error("Date invalide : %s", sys.argv[1])
            sys.exit(1)
    else:
        target = date.today() + timedelta(days=1)

    run(target)
