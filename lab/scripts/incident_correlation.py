
from configuration_change import compare_port_snapshots
from change_impact import analyze_change_impact
from change_timing import assess_change_timing


def correlate_incident(
    before_snapshot,
    after_snapshot,
    incident,
    before_time,
    after_time,
    incident_first_observed_at,
):
    change = compare_port_snapshots(
        before_snapshot, after_snapshot
    )

    impact = analyze_change_impact(change, incident)

    timing = assess_change_timing(
        before_time,
        after_time,
        incident_first_observed_at,
    )

    impact_status = impact["status"]
    timing_status = timing["status"]

    if impact_status == "no_change":
        assessment = "no_change_detected"
        conclusion = (
            "No configuration change was detected "
            "between these snapshots."
        )

    elif impact_status in (
        "not_on_path",
        "no_direct_impact_found",
    ):
        assessment = "no_direct_link_found"
        conclusion = (
            "Current path and VLAN evidence does not "
            "support a direct link to this incident."
        )

    elif impact_status == "needs_review":
        assessment = "needs_more_evidence"
        conclusion = (
            "Configuration evidence requires further "
            "review before assessing impact."
        )

    elif timing_status == "after_first_observation":
        assessment = "not_initial_trigger"
        conclusion = (
            "The change occurred after the incident "
            "was first observed, so it cannot explain "
            "the initial observation."
        )

    elif timing_status == "timing_uncertain":
        assessment = "timing_uncertain"
        conclusion = (
            "The change could affect this service, "
            "but event ordering is uncertain."
        )

    elif impact_status == "potential_impact":
        assessment = "candidate_for_investigation"
        conclusion = (
            "The change could affect the investigated "
            "service and preceded its first observation. "
            "Causation is not established."
        )

    else:
        assessment = "needs_more_evidence"
        conclusion = (
            "Available evidence is insufficient "
            "for a reliable correlation assessment."
        )

    return {
        "assessment": assessment,
        "configuration_change": change,
        "network_impact": impact,
        "timing": timing,
        "conclusion": conclusion,
    }
