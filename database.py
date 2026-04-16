"""
database.py — Toutes les opérations SQLite de l'application.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "pre_interventions.db"


# ─── Connexion ─────────────────────────────────────────────

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# ─── Initialisation ────────────────────────────────────────

def init_db() -> None:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS pre_interventions (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL,
            status              TEXT,
            completion_score    INTEGER,
            client_name         TEXT,
            address             TEXT,
            contact_name        TEXT,
            contact_phone       TEXT,
            scheduled_datetime  TEXT,
            service_call        TEXT,
            assigned_technician TEXT,
            intervention_goal   TEXT,
            systems_present_json TEXT,
            payload_json        TEXT NOT NULL,
            ai_output_json      TEXT,
            pdf_filename        TEXT,
            version             INTEGER DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS real_interventions (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            pre_intervention_id INTEGER NOT NULL,
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL,
            intervention_date   TEXT,
            technician_name     TEXT,
            resolution_status   TEXT,
            work_done           TEXT,
            real_root_cause     TEXT,
            real_actions_taken  TEXT,
            parts_used          TEXT,
            time_spent_minutes  INTEGER,
            follow_up_required  TEXT,
            follow_up_notes     TEXT,
            raw_source_json     TEXT,
            UNIQUE(pre_intervention_id),
            FOREIGN KEY(pre_intervention_id) REFERENCES pre_interventions(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS reconciliation_feedback (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            pre_intervention_id  INTEGER NOT NULL,
            real_intervention_id INTEGER,
            created_at           TEXT NOT NULL,
            updated_at           TEXT NOT NULL,
            hypotheses_hit_score    INTEGER,
            checks_relevance_score  INTEGER,
            plan_relevance_score    INTEGER,
            missing_critical_info   TEXT,
            notes                   TEXT,
            UNIQUE(pre_intervention_id),
            FOREIGN KEY(pre_intervention_id) REFERENCES pre_interventions(id),
            FOREIGN KEY(real_intervention_id) REFERENCES real_interventions(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS dispatch_log (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp      TEXT NOT NULL,
            technician     TEXT NOT NULL,
            dispatch_date  TEXT NOT NULL,
            status         TEXT NOT NULL,
            details        TEXT
        )
    """)

    conn.commit()
    conn.close()


# ─── Pré-interventions ─────────────────────────────────────

def save_pre_intervention(payload: Dict[str, Any], existing_id: Optional[int] = None) -> int:
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.now().isoformat(timespec="seconds")

    mandat   = payload["mandat"]
    technique = payload["technique"]
    ai_output = payload.get("ai_output", {})

    values = {
        "updated_at":           now,
        "status":               payload["meta"].get("status", "Brouillon"),
        "completion_score":     payload["meta"].get("completion_score", 0),
        "client_name":         mandat.get("client_name", ""),
        "address":             mandat.get("address", ""),
        "contact_name":        mandat.get("contact_name", ""),
        "contact_phone":       mandat.get("contact_phone", ""),
        "scheduled_datetime":  mandat.get("scheduled_datetime", ""),
        "service_call":        mandat.get("service_call", ""),
        "assigned_technician": mandat.get("assigned_technician", ""),
        "intervention_goal":   mandat.get("intervention_goal", ""),
        "systems_present_json": json.dumps(technique.get("systems_present", []), ensure_ascii=False),
        "payload_json":         json.dumps(payload, ensure_ascii=False),
        "ai_output_json":       json.dumps(ai_output, ensure_ascii=False),
    }

    if existing_id:
        cur.execute("""
            UPDATE pre_interventions
            SET updated_at=:updated_at, status=:status, completion_score=:completion_score,
                client_name=:client_name, address=:address, contact_name=:contact_name,
                contact_phone=:contact_phone, scheduled_datetime=:scheduled_datetime,
                service_call=:service_call, assigned_technician=:assigned_technician,
                intervention_goal=:intervention_goal,
                systems_present_json=:systems_present_json,
                payload_json=:payload_json, ai_output_json=:ai_output_json,
                version=version+1
            WHERE id=:id
        """, {**values, "id": existing_id})
        conn.commit()
        conn.close()
        return existing_id

    cur.execute("""
        INSERT INTO pre_interventions (
            created_at, updated_at, status, completion_score, client_name, address,
            contact_name, contact_phone, scheduled_datetime, service_call,
            assigned_technician, intervention_goal, systems_present_json,
            payload_json, ai_output_json
        ) VALUES (
            :created_at, :updated_at, :status, :completion_score, :client_name, :address,
            :contact_name, :contact_phone, :scheduled_datetime, :service_call,
            :assigned_technician, :intervention_goal, :systems_present_json,
            :payload_json, :ai_output_json
        )
    """, {**values, "created_at": now})
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    return int(new_id)


def list_pre_interventions(search: str = "") -> List[sqlite3.Row]:
    conn = get_conn()
    cur = conn.cursor()
    if search.strip():
        q = f"%{search.strip()}%"
        rows = cur.execute("""
            SELECT id, updated_at, client_name, service_call, scheduled_datetime,
                   status, completion_score, assigned_technician
            FROM pre_interventions
            WHERE client_name LIKE ? OR service_call LIKE ? OR assigned_technician LIKE ?
            ORDER BY updated_at DESC LIMIT 200
        """, (q, q, q)).fetchall()
    else:
        rows = cur.execute("""
            SELECT id, updated_at, client_name, service_call, scheduled_datetime,
                   status, completion_score, assigned_technician
            FROM pre_interventions ORDER BY updated_at DESC LIMIT 200
        """).fetchall()
    conn.close()
    return rows


def get_pre_intervention(pre_id: int) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM pre_interventions WHERE id=?", (pre_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ─── Interventions réelles ─────────────────────────────────

def upsert_real_intervention(pre_intervention_id: int, data: Dict[str, Any]) -> int:
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.now().isoformat(timespec="seconds")
    existing = cur.execute(
        "SELECT id FROM real_interventions WHERE pre_intervention_id=?",
        (pre_intervention_id,),
    ).fetchone()

    fields = (
        now,
        data.get("intervention_date", ""),
        data.get("technician_name", ""),
        data.get("resolution_status", ""),
        data.get("work_done", ""),
        data.get("real_root_cause", ""),
        data.get("real_actions_taken", ""),
        data.get("parts_used", ""),
        data.get("time_spent_minutes"),
        data.get("follow_up_required", ""),
        data.get("follow_up_notes", ""),
        json.dumps(data, ensure_ascii=False),
    )

    if existing:
        cur.execute("""
            UPDATE real_interventions
            SET updated_at=?, intervention_date=?, technician_name=?, resolution_status=?,
                work_done=?, real_root_cause=?, real_actions_taken=?, parts_used=?,
                time_spent_minutes=?, follow_up_required=?, follow_up_notes=?, raw_source_json=?
            WHERE pre_intervention_id=?
        """, (*fields, pre_intervention_id))
        conn.commit()
        real_id = int(existing["id"])
        conn.close()
        return real_id

    cur.execute("""
        INSERT INTO real_interventions (
            pre_intervention_id, created_at, updated_at, intervention_date,
            technician_name, resolution_status, work_done, real_root_cause,
            real_actions_taken, parts_used, time_spent_minutes,
            follow_up_required, follow_up_notes, raw_source_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (pre_intervention_id, now, *fields))
    real_id = cur.lastrowid
    conn.commit()
    conn.close()
    return int(real_id)


def get_real_intervention(pre_intervention_id: int) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM real_interventions WHERE pre_intervention_id=?",
        (pre_intervention_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ─── Dispatch ──────────────────────────────────────────────

def get_dispatch_for_day(date_str: str) -> Dict[str, List[Dict[str, Any]]]:
    conn = get_conn()
    rows = conn.execute("""
        SELECT id, client_name, address, scheduled_datetime,
               service_call, assigned_technician, intervention_goal, payload_json
        FROM pre_interventions
        WHERE scheduled_datetime LIKE ? || '%'
        ORDER BY scheduled_datetime ASC
    """, (date_str,)).fetchall()
    conn.close()

    dispatch: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        item = dict(r)
        tech_raw = item.get("assigned_technician") or ""
        techs = [t.strip() for t in tech_raw.split(",") if t.strip()] or ["Non assigné"]
        for tech in techs:
            dispatch.setdefault(tech, []).append(item)
    return dispatch


def log_dispatch(technician: str, dispatch_date: str, status: str, details: str = "") -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO dispatch_log (timestamp, technician, dispatch_date, status, details) VALUES (?,?,?,?,?)",
        (datetime.now().isoformat(timespec="seconds"), technician, dispatch_date, status, details),
    )
    conn.commit()
    conn.close()
