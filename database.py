"""
Couche de stockage SQLite pour GrindBot.
Toutes les dates de semaine ('week_start') sont stockées au format
'YYYY-MM-DD' et correspondent au LUNDI de la semaine concernée.
"""
import sqlite3
from datetime import date, timedelta
from contextlib import contextmanager

from config import DB_PATH


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                discord_id INTEGER PRIMARY KEY,
                thread_id INTEGER,
                missed_weeks INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS objectives (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id INTEGER NOT NULL,
                week_start TEXT NOT NULL,
                type TEXT NOT NULL,       -- 'objectif' ou 'habitude'
                text TEXT NOT NULL,
                target INTEGER,           -- nb de jours/semaine visés (habitudes uniquement)
                done INTEGER NOT NULL DEFAULT 0   -- objectifs uniquement : 0/1
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS checkins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id INTEGER NOT NULL,
                checkin_date TEXT NOT NULL,
                objective_id INTEGER,     -- NULL si freestyle (pas d'objectifs cette semaine)
                status TEXT NOT NULL,     -- '✅'/'❌' (habitude), texte libre (objectif/freestyle)
                motivation INTEGER
            )
        """)


# ---------- Semaines ----------

def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def upcoming_week_start(today: date) -> str:
    """Lundi de la semaine qui commence après le dimanche en cours (ou aujourd'hui si on est déjà lundi)."""
    monday = monday_of(today)
    if today.weekday() == 6:  # dimanche -> semaine suivante
        monday = monday + timedelta(days=7)
    return monday.isoformat()


def current_week_start(today: date) -> str:
    return monday_of(today).isoformat()


# ---------- Users / threads ----------

def ensure_user(discord_id: int):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (discord_id, thread_id, missed_weeks) VALUES (?, NULL, 0)",
            (discord_id,),
        )


def set_thread(discord_id: int, thread_id: int):
    ensure_user(discord_id)
    with get_conn() as conn:
        conn.execute("UPDATE users SET thread_id = ? WHERE discord_id = ?", (thread_id, discord_id))


def get_thread(discord_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT thread_id FROM users WHERE discord_id = ?", (discord_id,)).fetchone()
        return row["thread_id"] if row and row["thread_id"] else None


def get_all_users():
    with get_conn() as conn:
        return [r["discord_id"] for r in conn.execute("SELECT discord_id FROM users WHERE thread_id IS NOT NULL")]


def get_missed(discord_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT missed_weeks FROM users WHERE discord_id = ?", (discord_id,)).fetchone()
        return row["missed_weeks"] if row else 0


def increment_missed(discord_id: int):
    ensure_user(discord_id)
    with get_conn() as conn:
        conn.execute("UPDATE users SET missed_weeks = missed_weeks + 1 WHERE discord_id = ?", (discord_id,))


def reset_missed(discord_id: int):
    ensure_user(discord_id)
    with get_conn() as conn:
        conn.execute("UPDATE users SET missed_weeks = 0 WHERE discord_id = ?", (discord_id,))


# ---------- Objectifs ----------

def add_objective(discord_id: int, week_start: str, obj_type: str, text: str, target: int = None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO objectives (discord_id, week_start, type, text, target, done) VALUES (?, ?, ?, ?, ?, 0)",
            (discord_id, week_start, obj_type, text, target),
        )


def get_objectives(discord_id: int, week_start: str):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM objectives WHERE discord_id = ? AND week_start = ? ORDER BY id",
            (discord_id, week_start),
        ).fetchall()


def has_objectives(discord_id: int, week_start: str) -> bool:
    return len(get_objectives(discord_id, week_start)) > 0


def mark_objective_done(objective_id: int, done: bool = True):
    with get_conn() as conn:
        conn.execute("UPDATE objectives SET done = ? WHERE id = ?", (1 if done else 0, objective_id))


def clear_objectives(discord_id: int, week_start: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM objectives WHERE discord_id = ? AND week_start = ?", (discord_id, week_start))


# ---------- Check-ins ----------

def add_checkin(discord_id: int, checkin_date: str, objective_id, status: str, motivation: int = None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO checkins (discord_id, checkin_date, objective_id, status, motivation) VALUES (?, ?, ?, ?, ?)",
            (discord_id, checkin_date, objective_id, status, motivation),
        )


def get_checkins_for_week(discord_id: int, week_start: str):
    monday = date.fromisoformat(week_start)
    saturday = monday + timedelta(days=5)
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM checkins WHERE discord_id = ? AND checkin_date BETWEEN ? AND ? ORDER BY checkin_date",
            (discord_id, monday.isoformat(), saturday.isoformat()),
        ).fetchall()


def already_checked_in_today(discord_id: int, checkin_date: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM checkins WHERE discord_id = ? AND checkin_date = ? LIMIT 1",
            (discord_id, checkin_date),
        ).fetchone()
        return row is not None