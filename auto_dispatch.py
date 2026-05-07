"""
auto_dispatch.py — Envoi automatique des emails de dispatch la veille.

Usage (planifier via Windows Task Scheduler) :
    python auto_dispatch.py              → dispatch pour DEMAIN
    python auto_dispatch.py 2026-05-08   → dispatch pour la date spécifiée

Le script envoie uniquement aux techniciens qui n'ont PAS encore reçu
d'email pour cette journée (send_count == 0). Si tous sont déjà
dispatchés, aucun envoi n'est effectué.

Variables d'environnement requises (ou dans .env) :
    BREVO_API_KEY        clé API Brevo
    BREVO_SENDER_EMAIL   adresse expéditeur
"""
from __future__ import annotations

import sys
import logging
from datetime import date, timedelta
from pathlib import Path

# ── Chargement .env ────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

# ── Modules internes ───────────────────────────────────────
from database import init_db, get_dispatch_for_day, get_dispatch_send_count
from dispatch import send_dispatch_emails
from config import TECH_EMAIL_MAP
from utils import format_french_date

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            Path(__file__).resolve().parent / "data" / "auto_dispatch.log",
            encoding="utf-8",
        ),
    ],
)
log = logging.getLogger(__name__)


def run(target_date: date) -> None:
    date_str = target_date.strftime("%Y-%m-%d")
    readable = format_french_date(date_str)
    log.info("=== Auto-dispatch pour le %s ===", readable)

    init_db()
    dispatch_data = get_dispatch_for_day(date_str)

    if not dispatch_data:
        log.info("Aucun appel planifié pour le %s — rien à envoyer.", readable)
        return

    # Filtrer les techniciens qui n'ont PAS encore reçu d'email ce jour-là
    not_yet_sent = {
        tech: calls
        for tech, calls in dispatch_data.items()
        if get_dispatch_send_count(tech, date_str) == 0
    }

    already_sent = set(dispatch_data) - set(not_yet_sent)
    if already_sent:
        log.info(
            "Déjà dispatchés (ignorés) : %s",
            ", ".join(sorted(already_sent)),
        )

    if not not_yet_sent:
        log.info("Tous les techniciens sont déjà dispatchés pour le %s.", readable)
        return

    log.info(
        "Envoi pour %d technicien(s) : %s",
        len(not_yet_sent),
        ", ".join(sorted(not_yet_sent)),
    )

    # CC fixe vers le service (peut être vidé si indésirable)
    cc_map = {tech: "service@groupecs.com" for tech in not_yet_sent}

    results = send_dispatch_emails(not_yet_sent, date_str, TECH_EMAIL_MAP, cc_map)

    ok = err = skipped = 0
    for r in results:
        if r["status"] == "success":
            log.info("  ✓ %s — envoyé", r["tech"])
            ok += 1
        elif r["status"] == "skipped":
            log.warning("  ⏭ %s — ignoré : %s", r["tech"], r["message"])
            skipped += 1
        else:
            log.error("  ✗ %s — erreur : %s", r["tech"], r["message"])
            err += 1

    log.info(
        "Terminé — OK: %d | Ignorés: %d | Erreurs: %d",
        ok, skipped, err,
    )


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        try:
            target = date.fromisoformat(sys.argv[1])
        except ValueError:
            log.error("Date invalide : %s (format attendu : YYYY-MM-DD)", sys.argv[1])
            sys.exit(1)
    else:
        target = date.today() + timedelta(days=1)

    run(target)
