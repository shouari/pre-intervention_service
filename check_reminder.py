"""
check_reminder.py — Vérifie si un rappel email doit être envoyé.

Planifier via Windows Task Scheduler toutes les 15 minutes.
Le rappel part 1h après le dernier fetch batch si des SC
de la journée fetchée ne sont pas préparés.

Critères "non préparé" (un seul suffit) :
    - completion_score < 70
    - intervention_goal vide ou null
    - assigned_technician vide ou null

Idempotent : un seul email par journée cible, même si le script
tourne plusieurs fois après le délai.

Variables d'environnement requises (ou dans .env) :
    BREVO_API_KEY
    BREVO_SENDER_EMAIL
"""
from __future__ import annotations

import json
import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

from database import init_db, get_setting
from reminder_unprepared import (
    get_unprepared_calls,
    reminder_already_sent,
    send_reminder_email,
    log_reminder_sent,
)
from utils import format_french_date

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

REMINDER_DELAY_MINUTES = 60   # délai après le fetch avant d'envoyer


def run() -> None:
    init_db()

    # ── Lire les settings ──────────────────────────────────
    last_fetch_at_str = get_setting("last_fetch_at")
    last_fetch_date   = get_setting("last_fetch_date")

    if not last_fetch_at_str or not last_fetch_date:
        log.info("Aucun fetch enregistré — rien à faire.")
        return

    # ── Vérifier le délai ─────────────────────────────────
    try:
        last_fetch_at = datetime.fromisoformat(last_fetch_at_str)
    except ValueError:
        log.error("Format last_fetch_at invalide : %s", last_fetch_at_str)
        return

    elapsed   = datetime.now() - last_fetch_at
    remaining = timedelta(minutes=REMINDER_DELAY_MINUTES) - elapsed

    if remaining > timedelta(0):
        mins = int(remaining.total_seconds() / 60)
        log.info(
            "Délai non écoulé — rappel dans ~%d min (fetch: %s).",
            mins, last_fetch_at_str[:16],
        )
        return

    # ── Vérifier si déjà envoyé aujourd'hui ───────────────
    if reminder_already_sent(last_fetch_date):
        log.info(
            "Rappel déjà envoyé pour le %s — ignoré.",
            format_french_date(last_fetch_date),
        )
        return

    # ── Vérifier s'il y a des SC non préparés ─────────────
    unprepared = get_unprepared_calls(last_fetch_date)

    if not unprepared:
        log.info(
            "Tous les appels du %s sont préparés — aucun rappel.",
            format_french_date(last_fetch_date),
        )
        return

    # ── Envoyer l'email ───────────────────────────────────
    log.info(
        "%d SC non préparé(s) pour le %s — envoi du rappel…",
        len(unprepared), format_french_date(last_fetch_date),
    )
    for c in unprepared:
        log.info(
            "  · %s — %s (score: %s%%)",
            c.get("service_call"), c.get("client_name"), c.get("completion_score"),
        )

    success = send_reminder_email(last_fetch_date, unprepared)

    if success:
        log.info("✓ Email de rappel envoyé à service@groupecs.com.")
        log_reminder_sent(
            last_fetch_date,
            json.dumps({
                "trigger":   "post_fetch",
                "delay_min": REMINDER_DELAY_MINUTES,
                "fetch_at":  last_fetch_at_str,
                "count":     len(unprepared),
                "calls":     [c.get("service_call") for c in unprepared],
            }, ensure_ascii=False),
        )
    else:
        log.error("✗ Échec de l'envoi du rappel.")


if __name__ == "__main__":
    run()
