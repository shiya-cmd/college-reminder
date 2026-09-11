import sqlite3
from config import DB_PATH

def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    with connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                telegram_user_id INTEGER PRIMARY KEY,
                username TEXT NOT NULL,
                password_encrypted TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER NOT NULL,
                event_id TEXT NOT NULL,
                course_id TEXT,
                title TEXT NOT NULL,
                url TEXT,
                due REAL,
                first_seen REAL NOT NULL,
                new_alert_sent INTEGER NOT NULL DEFAULT 0,
                reminder_10_sent INTEGER NOT NULL DEFAULT 0,
                reminder_2_sent INTEGER NOT NULL DEFAULT 0,
                completed INTEGER NOT NULL DEFAULT 0,
                UNIQUE(telegram_user_id, event_id)
            )
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_assignments_due
            ON assignments(telegram_user_id, due)
        """)
        db.commit()

def get_account(user_id):
    with connect() as db:
        return db.execute(
            "SELECT * FROM accounts WHERE telegram_user_id=?",
            (user_id,)
        ).fetchone()

def save_account(user_id, username, encrypted_password, now):
    with connect() as db:
        db.execute("""
            INSERT INTO accounts
            (telegram_user_id, username, password_encrypted, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                username=excluded.username,
                password_encrypted=excluded.password_encrypted,
                updated_at=excluded.updated_at
        """, (user_id, username, encrypted_password, now, now))
        db.commit()

def delete_account(user_id):
    with connect() as db:
        db.execute("DELETE FROM accounts WHERE telegram_user_id=?", (user_id,))
        db.execute("DELETE FROM assignments WHERE telegram_user_id=?", (user_id,))
        db.commit()

def upsert_assignment(user_id, assignment, now):
    with connect() as db:
        existing = db.execute("""
            SELECT * FROM assignments
            WHERE telegram_user_id=? AND event_id=?
        """, (user_id, str(assignment["event_id"]))).fetchone()

        if existing:
            db.execute("""
                UPDATE assignments
                SET course_id=?, title=?, url=?, due=?
                WHERE telegram_user_id=? AND event_id=?
            """, (
                assignment.get("course_id"),
                assignment.get("title") or "Untitled assignment",
                assignment.get("url"),
                assignment.get("due"),
                user_id,
                str(assignment["event_id"])
            ))
            db.commit()
            return False

        db.execute("""
            INSERT INTO assignments
            (telegram_user_id, event_id, course_id, title, url, due, first_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            str(assignment["event_id"]),
            assignment.get("course_id"),
            assignment.get("title") or "Untitled assignment",
            assignment.get("url"),
            assignment.get("due"),
            now
        ))
        db.commit()
        return True

def get_assignments(user_id, include_completed=False):
    with connect() as db:
        if include_completed:
            return db.execute("""
                SELECT * FROM assignments
                WHERE telegram_user_id=?
                ORDER BY
                    CASE WHEN due IS NULL THEN 1 ELSE 0 END,
                    due ASC
            """, (user_id,)).fetchall()

        return db.execute("""
            SELECT * FROM assignments
            WHERE telegram_user_id=? AND completed=0
            ORDER BY
                CASE WHEN due IS NULL THEN 1 ELSE 0 END,
                due ASC
        """, (user_id,)).fetchall()

def get_assignment(user_id, assignment_id):
    with connect() as db:
        return db.execute("""
            SELECT * FROM assignments
            WHERE telegram_user_id=? AND id=?
        """, (user_id, assignment_id)).fetchone()

def mark_completed(user_id, assignment_id):
    with connect() as db:
        cur = db.execute("""
            UPDATE assignments
            SET completed=1
            WHERE telegram_user_id=? AND id=?
        """, (user_id, assignment_id))
        db.commit()
        return cur.rowcount > 0

def get_users():
    with connect() as db:
        return [
            row["telegram_user_id"]
            for row in db.execute("SELECT telegram_user_id FROM accounts")
        ]

def get_pending_reminders(user_id, now):
    with connect() as db:
        return db.execute("""
            SELECT * FROM assignments
            WHERE telegram_user_id=?
              AND completed=0
              AND due IS NOT NULL
              AND due > ?
              AND due <= ?
            ORDER BY due ASC
        """, (user_id, now, now + 11 * 3600)).fetchall()

def mark_new_alert_sent(user_id, assignment_id):
    with connect() as db:
        db.execute("""
            UPDATE assignments
            SET new_alert_sent=1
            WHERE telegram_user_id=? AND id=?
        """, (user_id, assignment_id))
        db.commit()

def mark_reminder_sent(user_id, assignment_id, reminder):
    column = "reminder_10_sent" if reminder == 10 else "reminder_2_sent"
    with connect() as db:
        db.execute(
            f"UPDATE assignments SET {column}=1 WHERE telegram_user_id=? AND id=?",
            (user_id, assignment_id)
        )
        db.commit()
