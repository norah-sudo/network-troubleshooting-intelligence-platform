
def diagnose_trunk(switch, port, expected, observed):

    if expected.get("mode") != "trunk":
        raise ValueError("This rule requires a trunk baseline")

    # Missing or incorrect evidence
    if not isinstance(observed, dict):
        return {
            "device": switch,
            "port": port,
            "status": "insufficient_evidence",
            "issue": "Trunk evidence unavailable",
            "recommendation": "Collect fresh switch port evidence.",
        }

    if observed.get("name") != port:
        return {
            "device": switch,
            "port": port,
            "status": "insufficient_evidence",
            "issue": "Unexpected port in evidence",
            "recommendation": "Verify the port evidence.",
        }

    # Check trunk mode
    if observed.get("mode") != "trunk":
        return {
            "device": switch,
            "port": port,
            "status": "configuration_mismatch",
            "issue": "Port is not configured as a trunk",
            "recommendation": "Review the port VLAN mode.",
        }

    expected_vlans = expected["vlans"]
    observed_vlans = observed.get("vlans")

    if not isinstance(observed_vlans, list):
        return {
            "device": switch,
            "port": port,
            "status": "insufficient_evidence",
            "issue": "Invalid trunk VLAN evidence",
            "recommendation": "Collect valid trunk configuration.",
        }

    # In OVS, an empty trunks list can mean unrestricted VLANs
    if not observed_vlans:
        return {
            "device": switch,
            "port": port,
            "status": "configuration_mismatch",
            "issue": "Trunk VLAN list is unrestricted",
            "recommendation": "Review allowed VLAN restrictions.",
        }

    missing_vlans = sorted(
        set(expected_vlans) - set(observed_vlans)
    )

    # Expected VLANs are missing
    if missing_vlans:
        return {
            "device": switch,
            "port": port,
            "status": "fault_detected",
            "issue": "Expected VLANs missing from trunk",
            "evidence": {
                "expected": expected_vlans,
                "observed": observed_vlans,
                "missing_vlans": missing_vlans,
            },
            "possible_cause": (
                "The trunk VLAN configuration differs "
                "from the expected network baseline."
            ),
            "recommendation": (
                "Review trunk configuration and restore "
                "the missing VLANs if required."
            ),
        }

    # Unexpected additional VLANs
    if set(observed_vlans) != set(expected_vlans):
        return {
            "device": switch,
            "port": port,
            "status": "configuration_mismatch",
            "issue": "Unexpected VLANs allowed on trunk",
            "recommendation": "Review trunk VLAN restrictions.",
        }

    return {
        "device": switch,
        "port": port,
        "status": "healthy",
        "issue": None,
        "recommendation": None,
    }
