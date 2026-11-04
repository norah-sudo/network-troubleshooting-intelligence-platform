
def diagnose_ospf(device, expected, interface, neighbors):
    # Missing or invalid evidence
    if not isinstance(interface, dict) or not isinstance(neighbors, list):
        return {
            "device": device,
            "status": "insufficient_evidence",
            "issue": "OSPF or interface evidence unavailable",
            "recommendation": "Collect fresh interface and OSPF evidence.",
        }

    # Verify that the interface evidence is for the right port
    if interface.get("interface") != expected["interface"]:
        return {
            "device": device,
            "status": "insufficient_evidence",
            "issue": "Unexpected interface evidence",
            "recommendation": "Verify the interface evidence.",
        }

    # Check the physical and protocol state first
    if (
        interface.get("interface_status") != "up"
        or interface.get("line_protocol") != "up"
    ):
        return {
            "device": device,
            "status": "interface_issue",
            "issue": "Interface is not UP/UP",
            "recommendation": "Investigate the interface before OSPF.",
        }

    # Look for the expected OSPF neighbor
    neighbor = next(
        (
            item for item in neighbors
            if item.get("neighbor_id") == expected["ospf_neighbor_id"]
        ),
        None,
    )

    if neighbor is None:
        return {
            "device": device,
            "status": "fault_detected",
            "issue": "Expected OSPF neighbor missing",
            "evidence": {
                "interface": "UP/UP",
                "expected_neighbor": expected["ospf_neighbor_id"],
                "observed_neighbors": neighbors,
            },
            "possible_cause": (
                "An OSPF configuration or adjacency problem is possible."
            ),
            "recommendation": (
                "Check OSPF configuration, peer connectivity, "
                "and OSPF event logs."
            ),
        }

    if neighbor.get("state") != expected["ospf_state"]:
        return {
            "device": device,
            "status": "fault_detected",
            "issue": "OSPF adjacency not in expected state",
            "evidence": {
                "expected_state": expected["ospf_state"],
                "observed_state": neighbor.get("state"),
                "neighbor_id": neighbor["neighbor_id"],
            },
            "possible_cause": (
                "The OSPF adjacency has not reached its expected state."
            ),
            "recommendation": (
                "Check OSPF neighbor state, timers, "
                "configuration, and recent events."
            ),
        }

    return {
        "device": device,
        "status": "healthy",
        "issue": None,
        "recommendation": None,
    }

def diagnose_ospf_with_syslog(
    db, device, expected, interface, neighbors, reference_time
):
    from syslog_correlation import get_related_ospf_events

    # First: diagnose interface and OSPF state
    report = diagnose_ospf(
        device, expected, interface, neighbors
    )

    # Only investigate Syslog when an OSPF fault is detected
    if report["status"] != "fault_detected":
        return report

    # Search for events near the evidence collection time
    events = get_related_ospf_events(
        db, device, reference_time
    )

    expected_neighbor = expected["ospf_neighbor_id"]

    related_events = []

    for event in events:
        # Neighbor events must mention the expected neighbor
        if event["category"] == "neighbor_event":
            if expected_neighbor in event["message"]:
                related_events.append(event)

        # Daemon events are useful context, not proof of failure
        elif event["category"] == "daemon_event":
            related_events.append(event)

    report["syslog_evidence"] = related_events

    return report
