
from datetime import datetime, timezone

from state_monitor import MAX_EVIDENCE_AGE_SECONDS


def get_latest_provenance(db, device, command):
    row = db.execute(
        """
        SELECT id, status, collected_at
        FROM evidence_records
        WHERE device = ? AND command = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (device, command),
    ).fetchone()

    if row is None:
        return {
            "record_id": None,
            "device": device,
            "command": command,
            "collection_status": "missing",
            "collected_at": None,
            "freshness": "missing",
        }

    record_id, status, collected_at = row

    try:
        timestamp = datetime.fromisoformat(collected_at)

        if timestamp.tzinfo is None:
            raise ValueError("Timezone missing")

        age = (
            datetime.now(timezone.utc) - timestamp
        ).total_seconds()

        if age < -30:
            freshness = "future_timestamp"
        elif age > MAX_EVIDENCE_AGE_SECONDS:
            freshness = "stale"
        else:
            freshness = "fresh"

    except (ValueError, TypeError):
        freshness = "invalid_timestamp"

    return {
        "record_id": record_id,
        "device": device,
        "command": command,
        "collection_status": status,
        "collected_at": collected_at,
        "freshness": freshness,
    }


def get_check_provenance(db, baseline, device, component):

    if device in baseline["routers"]:
        interface = baseline["routers"][device]["interface"]
        interface_command = f"show interface {interface}"

        if component == "interface":
            commands = [interface_command]

        elif component == "ospf":
            commands = [
                interface_command,
                "show ip ospf neighbor",
            ]

        else:
            raise ValueError(
                f"Unknown router check: {component}"
            )

    elif device in baseline["switches"]:
        if component not in baseline["switches"][device]:
            raise ValueError(
                f"Unknown switch port: {component}"
            )

        commands = [
            f"ovs-vsctl list Port {component}"
        ]

    else:
        raise ValueError(f"Unknown device: {device}")

    return [
        get_latest_provenance(db, device, command)
        for command in commands
    ]
