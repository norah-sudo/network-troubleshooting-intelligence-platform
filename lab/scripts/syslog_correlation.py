
import re
from datetime import datetime, timedelta


def get_related_ospf_events(db, device, reference_time, minutes=10):

    device_mapping = {
        "clab-ospftest-r1": "r1",
        "clab-ospftest-r2": "r2",
    }

    if device not in device_mapping:
        raise ValueError("Unknown network device")

    if minutes <= 0:
        raise ValueError("Invalid time window")

    reference = datetime.fromisoformat(
        reference_time.replace("Z", "+00:00")
    )

    if reference.tzinfo is None:
        raise ValueError("Reference time must include timezone")

    window_start = reference - timedelta(minutes=minutes)

    rows = db.execute(
        """
        SELECT event_time, message
        FROM syslog_events
        WHERE device = ?
        ORDER BY event_time DESC
        """,
        (device_mapping[device],),
    ).fetchall()

    related_events = []

    for event_time, message in rows:
        if not event_time:
            continue

        try:
            event_date = datetime.fromisoformat(
                event_time.replace("Z", "+00:00")
            )
        except ValueError:
            continue

        if event_date.tzinfo is None:
            continue

        if not window_start <= event_date <= reference:
            continue

        lower_message = message.lower()

        # Explicit OSPF neighbor or adjacency events
        if "ospf" in lower_message and re.search(
            r"\b(neighbor|neighbour|adjacency|nbr)\b",
            lower_message,
        ):
            category = "neighbor_event"

        # OSPF daemon events: context, not proof of neighbor failure
        elif "ospfd state ->" in lower_message:
            category = "daemon_event"

        else:
            continue

        related_events.append({
            "time": event_date.isoformat(),
            "category": category,
            "message": message,
        })

    return related_events
