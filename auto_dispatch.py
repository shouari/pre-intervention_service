"""
auto_dispatch.py — Envoi automatique des emails de dispatch la veille.

Usage (planifier via Windows Task Scheduler) :
    python auto_dispatch.py              → dispatch pour DEMAIN
    python auto_dispatch.py 2026-05-08   → dispatch pour la date spécifiée

Conditions d'envoi pour chaque technicien :
    1. Jamais dispatché ce jour-là (send_count == 0), OU
    2. Déjà dispatché mais des changements ont eu lieu depuis le dernier envoi
       (appels ajoutés, retirés, ou modifiés)

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
from database import init_db, get_dispatch_for_day, get_dispatch_send_count, get_last_dispatch_snapshot
from dispatch import send_dispatch_emails, _build_snapshot, _compute_changes, _format_changes
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


def _has_changes(tech: str, calls: list, date_str: str) -> tuple[bool, str]:
    """
    Retourne (True, description) si les appels ont changé depuis le dernier dispatch,
    (False, "") sinon.
    """
    prev_snapshot = get_last_dispatch_snapshot(tech, date_str)
    if prev_snapshot is None:
        return False, ""
    new_snapshot = _build_snapshot(calls)
    changes = _compute_changes(prev_snapshot, new_snapshot)
    has = bool(changes["added"] or changes["removed"] or changes["modified"])
    return has, _format_changes(changes) if has else ""


def run(target_date: date) -> None:
    date_str = target_date.strftime("%Y-%m-%d")
    readable = format_french_date(date_str)
    log.info("=== Auto-dispatch pour le %s ===", readable)

    init_db()
    dispatch_data = get_dispatch_for_day(date_str)

    if not dispatch_data:
        log.info("Aucun appel planifié pour le %s — rien à envoyer.", readable)
        return

    # Décider qui doit recevoir un email
    to_send: dict = {}
    for tech, calls in dispatch_data.items():
        send_count = get_dispatch_send_count(tech, date_str)

        if send_count == 0:
            log.info("  → %s : jamais dispatché — envoi initial", tech)
            to_send[tech] = calls
        else:
            changed, desc = _has_changes(tech, calls, date_str)
            if changed:
                log.info("  → %s : changements détectés (%s) — mise à jour", tech, desc)
                to_send[tech] = calls
            else:
                log.info("  ✓ %s : déjà dispatché, aucun changement — ignoré", tech)

    if not to_send:
        log.info("Aucun envoi nécessaire pour le %s.", readable)
        return

    log.info(
        "Envoi pour %d technicien(s) : %s",
        len(to_send),
        ", ".join(sorted(to_send)),
    )

    cc_map = {tech: "service@groupecs.com" for tech in to_send}
    results = send_dispatch_emails(to_send, date_str, TECH_EMAIL_MAP, cc_map)

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
