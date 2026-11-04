
from incident_correlation import correlate_incident


def attach_incident_correlation(
    report,
    incident_id,
    incident,
    before_snapshot,
    after_snapshot,
    before_time,
    after_time,
    incident_first_observed_at,
    source_type="real",
):
    if source_type not in ("real", "simulation"):
        raise ValueError("Invalid incident source type")

    if not incident_id:
        raise ValueError("Incident ID is required")

    correlation = correlate_incident(
        before_snapshot,
        after_snapshot,
        incident,
        before_time,
        after_time,
        incident_first_observed_at,
    )

    entry = {
        "incident_id": incident_id,
        "source_type": source_type,
        "incident": incident,
        "correlation": correlation,
    }

    report.setdefault(
        "incident_correlations", []
    ).append(entry)

    return report
