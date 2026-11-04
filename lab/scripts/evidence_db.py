
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "evidence.sqlite3"


def initialize_database():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(DB_PATH)

    try:
        # SSH and network-state evidence
        connection.execute("""
            CREATE TABLE IF NOT EXISTS evidence_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device TEXT NOT NULL,
                command TEXT NOT NULL,
                status TEXT NOT NULL
                    CHECK (status IN ('success', 'failed', 'timeout')),
                output TEXT NOT NULL,
                collected_at TEXT NOT NULL
            )
        """)

        # Network events collected through Syslog
        connection.execute("""
            CREATE TABLE IF NOT EXISTS syslog_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device TEXT NOT NULL,
                event_time TEXT,
                received_at TEXT NOT NULL,
                message TEXT NOT NULL,
                raw_line TEXT NOT NULL UNIQUE,
                imported_at TEXT NOT NULL
            )
        """)

        connection.commit()

    finally:
        connection.close()


if __name__ == "__main__":
    initialize_database()
    print("Database initialized:", DB_PATH)
