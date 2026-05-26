@echo off
REM ─────────────────────────────────────────────────────────────
REM  check_reminder — planifier via Windows Task Scheduler
REM  Fréquence recommandée : toutes les 15 minutes, toute la journée
REM
REM  Configuration Task Scheduler :
REM    Déclencheur : À l'heure de début, répéter toutes les 15 min
REM                  pendant 1 jour
REM    Action      : Démarrer ce programme
REM    Condition   : Démarrer uniquement si réseau disponible
REM
REM  Logique :
REM    - Lit last_fetch_at depuis la DB (écrit par app.py au batch import)
REM    - Si elapsed >= 60 min ET reminder pas encore envoyé aujourd'hui
REM      ET au moins 1 SC non préparé → envoie l'email
REM    - Sinon → exit silencieux
REM ─────────────────────────────────────────────────────────────

cd /d "%~dp0"
call .venv\Scripts\activate.bat
python check_reminder.py
REM pause
