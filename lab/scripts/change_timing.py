
from datetime import datetime


def assess_change_timing(
    before_time,
    after_time,
    incident_first_observed_at,
):
    def parse_time(value):
        timestamp = datetime.fromisoformat(value)

        if timestamp.tzinfo is None:
            raise ValueError("Timestamp must include timezone")

        return timestamp

    before = parse_time(before_time)
    after = parse_time(after_time)
    incident = parse_time(incident_first_observed_at)

    if after <= before:
        raise ValueError("Snapshot timestamps are not chronological")

    if after < incident:
        status = "before_first_observation"
        explanation = (
            "Configuration change was detected before "
            "the incident was first observed."
        )

    elif before > incident:
        status = "after_first_observation"
        explanation = (
            "Configuration change occurred after "
            "the incident was first observed."
        )

    else:
        status = "timing_uncertain"
        explanation = (
            "The incident observation overlaps the "
            "configuration change window. Exact order unknown."
        )

    return {
        "status": status,
        "change_window": {
            "after": before_time,
            "by": after_time,
        },
        "incident_first_observed_at": incident_first_observed_at,
        "explanation": explanation,
    }
