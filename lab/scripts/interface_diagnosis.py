
from state_comparator import compare_state


def diagnose_interface(device, expected, observed):
    fields = (
        "interface",
        "interface_status",
        "line_protocol",
    )

    reference = {
        field: expected[field]
        for field in fields
    }

    comparison = compare_state(reference, observed)

    # Missing or incomplete evidence
    if comparison["status"] == "insufficient_evidence":
        return {
            "device": device,
            "status": "insufficient_evidence",
            "issue": "Interface evidence unavailable",
            "possible_cause": None,
            "recommendation": "Collect fresh interface evidence.",
        }

    # Make sure evidence belongs to the expected interface
    if observed["interface"] != reference["interface"]:
        return {
            "device": device,
            "status": "insufficient_evidence",
            "issue": "Unexpected interface in evidence",
            "possible_cause": None,
            "recommendation": "Verify the device and interface.",
        }

    # Interface matches the healthy baseline
    if comparison["status"] == "match":
        return {
            "device": device,
            "status": "healthy",
            "issue": None,
            "possible_cause": None,
            "recommendation": None,
        }

    # Diagnose interface state
    if observed["interface_status"] == "administratively down":
        issue = "Interface administratively down"
        cause = "The interface is disabled in its configuration."
        action = "Verify whether the interface was intentionally shut down."

    elif observed["interface_status"] == "down":
        issue = "Interface down"
        cause = "A link or connectivity problem is possible."
        action = "Check the link, peer interface, and port configuration."

    elif observed["line_protocol"] == "down":
        issue = "Line protocol down"
        cause = "The interface is up, but the protocol is down."
        action = "Inspect the link state and peer configuration."

    else:
        return {
            "device": device,
            "status": "unclassified_mismatch",
            "issue": "Unexpected interface state",
            "possible_cause": None,
            "recommendation": "Review the collected interface evidence.",
        }

    return {
        "device": device,
        "interface": observed["interface"],
        "status": "fault_detected",
        "issue": issue,
        "evidence": {
            "expected": reference,
            "observed": observed,
        },
        "possible_cause": cause,
        "recommendation": action,
    }
