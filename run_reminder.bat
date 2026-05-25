@echo off
REM ─────────────────────────────────────────────────────────────
REM  Rappel appels non préparés — planifier via Windows Task Scheduler
REM  Heure recommandée : 13h00 chaque jour de semaine
REM  Envoie un email à service@groupecs.com si des appels de demain
REM  ont une complétion < 70%, un objectif vide, ou aucun technicien.
REM ─────────────────────────────────────────────────────────────

cd /d "%~dp0"
call .venv\Scripts\activate.bat
python reminder_unprepared.py
REM pause
