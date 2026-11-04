
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from evidence_db import DB_PATH, initialize_database

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "syslog.log"

# Recognize forwarded FRRouting messages from R1 and R2
SYSLOG_PATTERN = re.compile(
    r"^<\d+>1\s+(\S+)\s+(r1|r2)\s+frr-docker\s+-\s+-\s+-\s+(.*)$"
)

DOCKER_TIME_PATTERN = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)\s+(.*)$"
)


def import_syslog():
    initialize_database()


    if not LOG_PATH.exists():
        print("ERROR: Syslog file not found:", LOG_PATH)
        raise SystemExit(1)


    saved = 0
    skipped = 0

    connection = sqlite3.connect(DB_PATH)

    try:
        with LOG_PATH.open(encoding="utf-8", errors="replace") as log_file:
            for line in log_file:
                raw_line = line.rstrip("\r\n")

                parts = raw_line.split(" ", 2)
                if len(parts) != 3:
                    skipped += 1
                    continue

                received_at, _source_ip, payload = parts
                match = SYSLOG_PATTERN.match(payload)

                if not match:
                    skipped += 1
                    continue

                forwarded_at, device, body = match.groups()

                docker_event = DOCKER_TIME_PATTERN.match(body)

                if docker_event:
                    event_time = datetime.fromisoformat(
                        docker_event.group(1).replace("Z", "+00:00")
                    ).isoformat()
                    message = docker_event.group(2)
                else:
                    event_time = datetime.fromisoformat(
                        forwarded_at
                    ).astimezone(timezone.utc).isoformat()
                    message = body

                result = connection.execute(
                    """
                    INSERT OR IGNORE INTO syslog_events
                    (device, event_time, received_at, message,
                     raw_line, imported_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        device,
                        event_time,
                        received_at,
                        message,
                        raw_line,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )

                saved += result.rowcount

        connection.commit()

    finally:
        connection.close()

    print("New Syslog events saved:", saved)
    print("Unsupported lines skipped:", skipped)


if __name__ == "__main__":
    import_syslog()
