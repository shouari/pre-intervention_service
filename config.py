"""
config.py — Constantes globales de l'application.
Modifier CE fichier pour ajouter/retirer des techniciens, systèmes, etc.
"""

SYSTEM_OPTIONS = [
    "Unifi Networks",
    "Unifi Protect",
    "Unifi Access",
    "Control4",
    "Crestron",
    "Lutron",
    "QSC",
    "Logitech",
    "Hikvision",
    "Luma",
    "Paradox",
    "DSC",
    "CDVI",
    "Autre",
]

CONFIDENCE_OPTIONS = ["Faible", "Moyen", "Élevé"]

RESOLUTION_STATUS_OPTIONS = [
    "Résolu",
    "Partiellement résolu",
    "Non résolu",
    "Visite diagnostique seulement",
]

FOLLOW_UP_OPTIONS = ["Non", "Oui"]

# ─── Techniciens ───────────────────────────────────────────
# Source unique de vérité. Modifier ici pour ajouter/retirer un technicien.
TECHNICIANS: list[dict] = [
    {"first_name": "Alexandre", "last_name": "Langlois",         "email": "alanglois@groupecs.com"},
    {"first_name": "Blaise",    "last_name": "Cyr",              "email": "bdeschampscyr@groupecs.com"},
    {"first_name": "Matthieu",  "last_name": "Chizelle",         "email": "mchizelle@groupecs.com"},
    {"first_name": "Frederic",  "last_name": "Chabot",           "email": "fchabot@groupecs.com"},
    {"first_name": "Claude",    "last_name": "Tremblay",         "email": "ctremblay@groupecs.com"},
    {"first_name": "Simon",     "last_name": "Levesque",         "email": "slevesque@groupecs.com"},
    {"first_name": "Adlane",    "last_name": "Lamari",           "email": "alamari@groupecs.com"},
    {"first_name": "Jérémy",    "last_name": "Arbour",           "email": "jarbour@groupecs.com"},
    {"first_name": "Michael",   "last_name": "Samaan",           "email": "msamaan@groupecs.com"},
    {"first_name": "Djilali",   "last_name": "Nait Abdesselam",  "email": "dnaitabdesselam@groupecs.com"},
    {"first_name": "Eric",      "last_name": "Pilon",            "email": "epilon@groupecs.com"},
]

# Dérivés automatiquement — ne pas modifier manuellement
TECHNICIAN_LIST: list[str] = [f"{t['first_name']} {t['last_name']}" for t in TECHNICIANS]
TECH_EMAIL_MAP:  dict[str, str] = {f"{t['first_name']} {t['last_name']}": t["email"] for t in TECHNICIANS}
