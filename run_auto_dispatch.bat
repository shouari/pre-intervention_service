@echo off
REM ─────────────────────────────────────────────────────────────
REM  Auto-dispatch — à planifier via Windows Task Scheduler
REM  Heure recommandée : 17h00 ou 18h00 chaque jour de semaine
REM  Envoie les emails pour le lendemain aux techniciens non encore dispatchés.
REM ─────────────────────────────────────────────────────────────

cd /d "%~dp0"

REM Activer l'environnement virtuel
call .venv\Scripts\activate.bat

REM Lancer le script (sans argument = dispatch pour demain)
python auto_dispatch.py

REM Pause optionnelle pour voir les logs si lancé manuellement
REM pause
