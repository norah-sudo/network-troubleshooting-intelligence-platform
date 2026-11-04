import json
from contextlib import contextmanager

from diagnosis_report import print_report
from incident_report_integration import attach_incident_correlation

from mvp_vlan_runner import (
    LOG_DIR,
    PORTS,
    append_matrix_result,
    collect_and_diagnose,
    command,
    get_trunks,
    ping,
    set_trunks,
    utc_now,
    verify_healthy,
)


# VLAN 10 service path from the approved lab topology.
# This path is manually defined, not automatically discovered.
SERVICE_PATH = [
    "sw1p2",
    "sw1p1",
    "sw2p1",
    "sw2p2",
]


# --------------------------------------------------
# CONFIGURATION SNAPSHOTS
# --------------------------------------------------

def capture_port_snapshot(port):
    mode_result = command([
        "sudo", "-n", "ovs-vsctl",
        "get", "Port", port, "vlan_mode",
    ])

    mode = mode_result.stdout.strip().strip('"')
    vlans = json.loads(get_trunks(port))

    if not mode:
        raise RuntimeError("Port mode evidence is missing")

    if not isinstance(vlans, list) or not all(
        type(vlan) is int for vlan in vlans
    ):
        raise RuntimeError("Invalid trunk VLAN evidence")

    snapshot = {
        "name": port,
        "mode": mode,
        "vlans": vlans,
    }

    return snapshot, utc_now()


# --------------------------------------------------
# PROTECTED CONFIGURATION CHANGES
# --------------------------------------------------

@contextmanager
def protected_trunk_changes(allowed_ports=None):
    if allowed_ports is None:
        permitted_ports = set(PORTS)
    else:
        permitted_ports = set(allowed_ports)

        if permitted_ports != {"sw1p4", "sw2p1"}:
            raise ValueError("Unapproved S04 port scope")

    verify_healthy()
    saved = {}

    def change(port, vlans):
        if port not in permitted_ports:
            raise ValueError(f"Unapproved port: {port}")

        if not isinstance(vlans, list) or not all(
            type(vlan) is int for vlan in vlans
        ):
            raise ValueError("Invalid VLAN list")

        before, _ = capture_port_snapshot(port)

        if before["mode"] != "trunk":
            raise RuntimeError(
                f"Port {port} is not a trunk"
            )

        # Save the original configuration before modifying it.
        saved.setdefault(
            port,
            before["vlans"].copy(),
        )

        set_trunks(port, vlans)

        after, _ = capture_port_snapshot(port)

        if (
            after["mode"] != "trunk"
            or set(after["vlans"]) != set(vlans)
        ):
            raise RuntimeError(
                f"Fault configuration mismatch: {port}"
            )

        return after

    try:
        yield change

    finally:
        failures = []

        # Attempt restoration of every modified port.
        for port, original_vlans in reversed(
            list(saved.items())
        ):
            try:
                set_trunks(port, original_vlans)

                restored, _ = capture_port_snapshot(port)

                if (
                    restored["mode"] != "trunk"
                    or set(restored["vlans"]) != set(original_vlans)
                ):
                    raise RuntimeError(
                        "Restoration mismatch"
                    )

            except Exception as error:
                failures.append(
                    f"{port}: {error}"
                )

        # Confirm the complete network has recovered.
        try:
            verify_healthy()

        except Exception as error:
            failures.append(
                f"Health check: {error}"
            )

        if failures:
            raise RuntimeError(
                "Recovery failed: " + "; ".join(failures)
            )


# --------------------------------------------------
# INCIDENT CORRELATION
# --------------------------------------------------

def attach_s04_correlation(
    report,
    run_id,
    before_snapshot,
    after_snapshot,
    before_time,
    after_time,
    first_observed_at,
    failed_ping,
):
    # Require evidence of a real VLAN 10 connectivity failure.
    if (
        failed_ping.get("source") != "hr1"
        or failed_ping.get("destination") != "192.168.10.12"
        or failed_ping.get("packet_loss_pct") != 100.0
    ):
        raise RuntimeError(
            "A real VLAN 10 connectivity failure is required"
        )

    # Require a matching diagnosis finding.
    confirmed_fault = any(
        check.get("status") == "fault_detected"
        and check.get("device") in ("sw1", "sw2")
        and check.get("component") in ("sw1p1", "sw2p1")
        and isinstance(check.get("evidence"), dict)
        and 10 in check["evidence"].get("missing_vlans", [])
        for check in report.get("checks", [])
    )

    if not confirmed_fault:
        raise RuntimeError(
            "VLAN 10 fault not confirmed by diagnosis evidence"
        )

    attach_incident_correlation(
        report,
        run_id,
        {
            "vlan": 10,
            "path_ports": SERVICE_PATH,
        },
        before_snapshot,
        after_snapshot,
        before_time,
        after_time,
        first_observed_at,
        source_type="real",
    )

    print_report(report)

    return report["incident_correlations"][-1]["correlation"]


# --------------------------------------------------
# S04-F01: RELEVANT CHANGE BEFORE INCIDENT
# --------------------------------------------------

def run_s04_f01():
    with protected_trunk_changes() as change:

        # Snapshot before configuration change.
        before, before_time = capture_port_snapshot(
            "sw1p1"
        )

        # Temporarily remove VLAN 10 from the trunk.
        change("sw1p1", [20])

        # Snapshot after configuration change.
        after, after_time = capture_port_snapshot(
            "sw1p1"
        )

        # Verify VLAN 10 connectivity failure.
        failed_ping = ping(
            "hr1",
            "192.168.10.12",
        )

        first_observed_at = utc_now()

        # Verify VLAN 20 is unaffected.
        control_ping = ping(
            "it1",
            "192.168.20.12",
        )

        if failed_ping["packet_loss_pct"] != 100.0:
            raise RuntimeError(
                "Expected VLAN 10 outage not observed"
            )

        if control_ping["packet_loss_pct"] != 0.0:
            raise RuntimeError(
                "VLAN 20 control connectivity failed"
            )

        # Collect evidence and generate diagnosis.
        report, collection_s, report_s = (
            collect_and_diagnose()
        )

        if report["summary"]["total_checks"] != 12:
            raise RuntimeError(
                "Incomplete diagnosis report"
            )

        # Attach configuration-change correlation.
        correlation = attach_s04_correlation(
            report,
            "S04-F01",
            before,
            after,
            before_time,
            after_time,
            first_observed_at,
            failed_ping,
        )

        if (
            correlation["assessment"]
            != "candidate_for_investigation"
        ):
            raise RuntimeError(
                "Unexpected correlation assessment"
            )

    # Reaching here means the protected context exited
    # and recovery verification succeeded.
    return {
        "run_id": "S04-F01",
        "before_snapshot": before,
        "after_snapshot": after,
        "before_time": before_time,
        "after_time": after_time,
        "first_observed_at": first_observed_at,
        "failed_ping": failed_ping,
        "control_ping": control_ping,
        "collection_duration_s": collection_s,
        "report_duration_s": report_s,
        "correlation": correlation,
        "report": report,
        "recovery_verified": True,
    }


# --------------------------------------------------
# JSON + CSV RESULT SAVING
# --------------------------------------------------

def save_s04_result(result, row_builder):
    LOG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    log = LOG_DIR / f'{result["run_id"]}_result.json'

    # Serialize before opening the destination.
    payload = json.dumps(
        result,
        indent=2,
    ) + "\n"

    # Exclusive creation prevents overwriting existing results.
    with log.open(
        "x",
        encoding="utf-8",
    ) as file:
        file.write(payload)

    try:
        append_matrix_result(
            result,
            row_builder=row_builder,
        )

    except Exception as error:
        raise RuntimeError(
            f"JSON saved at {log}, but CSV registration failed. "
            f"Do not repeat the network fault. "
            f"Reconcile the saved JSON instead. Error: {error}"
        ) from error

    return log


# --------------------------------------------------
# S04-F01 TEST MATRIX ROW
# --------------------------------------------------

def build_s04_f01_matrix_row(result):
    if result["run_id"] != "S04-F01":
        raise ValueError(
            "Unexpected run ID"
        )

    correlation = result["correlation"]

    if (
        correlation["assessment"]
        != "candidate_for_investigation"
    ):
        raise RuntimeError(
            "Unexpected correlation assessment"
        )

    if result["recovery_verified"] is not True:
        raise RuntimeError(
            "Recovery was not verified"
        )

    evidence_ids = [
        str(source["record_id"])
        for check in result["report"]["checks"]
        for source in check.get("evidence_sources", [])
        if source.get("record_id") is not None
    ]

    if not evidence_ids:
        raise RuntimeError(
            "No diagnosis evidence IDs"
        )

    return {
        "run_id": "S04-F01",
        "scenario": "configuration_change_correlation",
        "variation": "remove_vlan10_sw1p1_before_observation",
        "expected_state": "faulty",
        "expected_fault_class": "missing_vlan_from_trunk",
        "expected_root_cause": "specific_cause_not_scored",
        "observed_status": "fault_detected",
        "observed_fault_class": "missing_vlan_from_trunk",
        "observed_root_cause": "unconfirmed",
        "detection_correct": "true",
        "diagnosis_correct": "not_applicable",
        "false_alarm": "false",
        "collection_status": "success",
        "evidence_record_ids": ";".join(
            dict.fromkeys(evidence_ids)
        ),
        "diagnosis_completed_at_utc": (
            result["report"]["generated_at"]
        ),
        "collection_duration_s": (
            result["collection_duration_s"]
        ),
        "report_duration_s": (
            result["report_duration_s"]
        ),
        "recovery_verified": "true",
        "notes": (
            "Expected correlation: candidate_for_investigation; "
            f"observed: {correlation['assessment']}; "
            f"snapshot window: {result['before_time']} to "
            f"{result['after_time']}; "
            f"failed ping observed: {result['first_observed_at']}; "
            "snapshots and ping evidence preserved in JSON; "
            "correlation does not establish causation; "
            "automatic detection latency not measured"
        ),
        "test_case_id": "S04-F01",
        "run_result": "passed",
    }
    # --------------------------------------------------
# S04-F02: UNRELATED CHANGE OUTSIDE SERVICE PATH
# --------------------------------------------------

def run_s04_f02():
    with protected_trunk_changes(
        allowed_ports={"sw1p4", "sw2p1"}
    ) as change:

        # Capture the unrelated port before the change.
        before, before_time = capture_port_snapshot(
            "sw1p4"
        )

        if (
            before["mode"] != "trunk"
            or set(before["vlans"]) != {10, 20}
        ):
            raise RuntimeError(
                "Unexpected sw1p4 baseline"
            )

        # Add unused VLAN 30 while retaining VLANs 10 and 20.
        change("sw1p4", [10, 20, 30])

        after, after_time = capture_port_snapshot(
            "sw1p4"
        )

        # Prove the unrelated change did not interrupt HR service.
        unaffected_ping = ping(
            "hr1",
            "192.168.10.12",
        )

        if unaffected_ping["packet_loss_pct"] != 0.0:
            raise RuntimeError(
                "HR connectivity affected by unrelated change"
            )

        # Inject the actual VLAN 10 fault on the service path.
        change("sw2p1", [20])

        failed_ping = ping(
            "hr1",
            "192.168.10.12",
        )

        first_observed_at = utc_now()

        control_ping = ping(
            "it1",
            "192.168.20.12",
        )

        if failed_ping["packet_loss_pct"] != 100.0:
            raise RuntimeError(
                "Expected VLAN 10 outage not observed"
            )

        if control_ping["packet_loss_pct"] != 0.0:
            raise RuntimeError(
                "VLAN 20 control connectivity failed"
            )

        # Collect fresh evidence and diagnose the network.
        report, collection_s, report_s = (
            collect_and_diagnose()
        )

        if report["summary"]["total_checks"] != 12:
            raise RuntimeError(
                "Incomplete diagnosis report"
            )

        # Require direct evidence of the real sw2p1 fault.
        confirmed_fault = any(
            check.get("device") == "sw2"
            and check.get("component") == "sw2p1"
            and check.get("status") == "fault_detected"
            and isinstance(check.get("evidence"), dict)
            and 10 in check["evidence"].get(
                "missing_vlans", []
            )
            for check in report["checks"]
        )

        if not confirmed_fault:
            raise RuntimeError(
                "Real sw2p1 VLAN 10 fault not confirmed"
            )

        # Correlate the incident with the unrelated sw1p4 change.
        correlation = attach_s04_correlation(
            report,
            "S04-F02",
            before,
            after,
            before_time,
            after_time,
            first_observed_at,
            failed_ping,
        )

        if (
            correlation["network_impact"]["status"]
            != "not_on_path"
        ):
            raise RuntimeError(
                "Unrelated port was incorrectly linked to path"
            )

        if (
            correlation["assessment"]
            != "no_direct_link_found"
        ):
            raise RuntimeError(
                "Unexpected correlation assessment"
            )

    # The protected context has completed recovery verification.
    return {
        "run_id": "S04-F02",
        "before_snapshot": before,
        "after_snapshot": after,
        "before_time": before_time,
        "after_time": after_time,
        "first_observed_at": first_observed_at,
        "unaffected_ping": unaffected_ping,
        "failed_ping": failed_ping,
        "control_ping": control_ping,
        "collection_duration_s": collection_s,
        "report_duration_s": report_s,
        "correlation": correlation,
        "report": report,
        "recovery_verified": True,
    }
# --------------------------------------------------
# S04-F02 TEST MATRIX ROW
# --------------------------------------------------

def build_s04_f02_matrix_row(result):
    if result.get("run_id") != "S04-F02":
        raise ValueError("Unexpected run ID")

    correlation = result["correlation"]

    if correlation["assessment"] != "no_direct_link_found":
        raise RuntimeError(
            "Unexpected correlation assessment"
        )

    if correlation["network_impact"]["status"] != "not_on_path":
        raise RuntimeError(
            "Expected outside-path impact assessment"
        )

    if result["recovery_verified"] is not True:
        raise RuntimeError(
            "Recovery was not verified"
        )

    before = result["before_snapshot"]
    after = result["after_snapshot"]

    if (
        before.get("name") != "sw1p4"
        or after.get("name") != "sw1p4"
        or set(before.get("vlans", [])) != {10, 20}
        or set(after.get("vlans", [])) != {10, 20, 30}
    ):
        raise RuntimeError(
            "Unexpected unrelated configuration change"
        )

    if result["unaffected_ping"]["packet_loss_pct"] != 0.0:
        raise RuntimeError(
            "Unrelated change affected HR connectivity"
        )

    if result["failed_ping"]["packet_loss_pct"] != 100.0:
        raise RuntimeError(
            "VLAN 10 outage was not confirmed"
        )

    if result["control_ping"]["packet_loss_pct"] != 0.0:
        raise RuntimeError(
            "VLAN 20 control failed"
        )

    # Confirm the actual fault is on sw2p1.
    fault_checks = [
        check
        for check in result["report"]["checks"]
        if (
            check.get("device") == "sw2"
            and check.get("component") == "sw2p1"
            and check.get("status") == "fault_detected"
            and isinstance(check.get("evidence"), dict)
            and 10 in check["evidence"].get(
                "missing_vlans", []
            )
        )
    ]

    if len(fault_checks) != 1:
        raise RuntimeError(
            "Expected sw2p1 fault evidence not found"
        )

    fault_record_ids = [
        source["record_id"]
        for check in fault_checks
        for source in check.get("evidence_sources", [])
        if source.get("record_id") is not None
    ]

    if not fault_record_ids:
        raise RuntimeError(
            "No evidence record IDs for sw2p1 fault"
        )

    evidence_ids = [
        str(source["record_id"])
        for check in result["report"]["checks"]
        for source in check.get("evidence_sources", [])
        if source.get("record_id") is not None
    ]

    return {
        "run_id": "S04-F02",
        "scenario": "configuration_change_correlation",
        "variation": "add_vlan30_sw1p4_fault_vlan10_sw2p1",
        "expected_state": "faulty",
        "expected_fault_class": "missing_vlan_from_trunk",
        "expected_root_cause": "specific_cause_not_scored",
        "observed_status": "fault_detected",
        "observed_fault_class": "missing_vlan_from_trunk",
        "observed_root_cause": "unconfirmed",
        "detection_correct": "true",
        "diagnosis_correct": "not_applicable",
        "false_alarm": "false",
        "collection_status": "success",
        "evidence_record_ids": ";".join(
            dict.fromkeys(evidence_ids)
        ),
        "fault_injected_at_utc": "",
        "first_detected_at_utc": "",
        "diagnosis_completed_at_utc": (
            result["report"]["generated_at"]
        ),
        "collection_duration_s": (
            result["collection_duration_s"]
        ),
        "report_duration_s": (
            result["report_duration_s"]
        ),
        "detection_latency_s": "",
        "diagnosis_latency_s": "",
        "recovery_verified": "true",
        "notes": (
            "Expected correlation: no_direct_link_found; "
            f"observed: {correlation['assessment']}; "
            "unrelated change on sw1p4 outside service path; "
            "VLAN 30 added while retaining VLANs 10 and 20; "
            "HR connectivity remained healthy before fault; "
            "actual VLAN 10 fault detected on sw2p1; "
            f"snapshot window: {result['before_time']} to "
            f"{result['after_time']}; "
            f"first observed failure: {result['first_observed_at']}; "
            "correlation does not establish causation; "
            "automatic detection latency not measured"
        ),
        "test_case_id": "S04-F02",
        "run_result": "passed",
    }
    # --------------------------------------------------
# S04-F03: CONFIGURATION CHANGE AFTER INCIDENT
# --------------------------------------------------

def run_s04_f03():
    with protected_trunk_changes() as change:

        # Verify the expected baseline before fault injection.
        for port in ("sw1p1", "sw2p1"):
            snapshot, _ = capture_port_snapshot(port)

            if (
                snapshot["mode"] != "trunk"
                or set(snapshot["vlans"]) != {10, 20}
            ):
                raise RuntimeError(
                    f"Unexpected baseline on {port}"
                )

        # Step 1: Create the actual incident on sw2p1.
        change("sw2p1", [20])

        # Step 2: Observe the incident BEFORE changing sw1p1.
        failed_ping = ping(
            "hr1",
            "192.168.10.12",
        )

        first_observed_at = utc_now()

        control_ping = ping(
            "it1",
            "192.168.20.12",
        )

        if failed_ping["packet_loss_pct"] != 100.0:
            raise RuntimeError(
                "Expected VLAN 10 outage not observed"
            )

        if control_ping["packet_loss_pct"] != 0.0:
            raise RuntimeError(
                "VLAN 20 control connectivity failed"
            )

        # Step 3: Capture sw1p1 AFTER incident observation.
        before, before_time = capture_port_snapshot(
            "sw1p1"
        )

        if (
            before["mode"] != "trunk"
            or set(before["vlans"]) != {10, 20}
        ):
            raise RuntimeError(
                "Unexpected sw1p1 baseline"
            )

        # Step 4: Make a relevant change AFTER the incident.
        change("sw1p1", [20])

        after, after_time = capture_port_snapshot(
            "sw1p1"
        )

        # Step 5: Collect fresh evidence.
        report, collection_s, report_s = (
            collect_and_diagnose()
        )

        if report["summary"]["total_checks"] != 12:
            raise RuntimeError(
                "Incomplete diagnosis report"
            )

        # Both VLAN 10 faults must be visible in the report.
        for device, port in (
            ("sw1", "sw1p1"),
            ("sw2", "sw2p1"),
        ):
            confirmed = any(
                check.get("device") == device
                and check.get("component") == port
                and check.get("status") == "fault_detected"
                and isinstance(check.get("evidence"), dict)
                and 10 in check["evidence"].get(
                    "missing_vlans", []
                )
                for check in report["checks"]
            )

            if not confirmed:
                raise RuntimeError(
                    f"VLAN 10 fault not confirmed on {port}"
                )

        # Step 6: Correlate the later sw1p1 change.
        correlation = attach_s04_correlation(
            report,
            "S04-F03",
            before,
            after,
            before_time,
            after_time,
            first_observed_at,
            failed_ping,
        )

        if (
            correlation["network_impact"]["status"]
            != "potential_impact"
        ):
            raise RuntimeError(
                "Expected potential network impact"
            )

        if (
            correlation["timing"]["status"]
            != "after_first_observation"
        ):
            raise RuntimeError(
                "Change was not confirmed after incident"
            )

        if (
            correlation["assessment"]
            != "not_initial_trigger"
        ):
            raise RuntimeError(
                "Unexpected correlation assessment"
            )

    # The protected context restores both ports and
    # verifies network health before reaching this return.
    return {
        "run_id": "S04-F03",
        "before_snapshot": before,
        "after_snapshot": after,
        "before_time": before_time,
        "after_time": after_time,
        "first_observed_at": first_observed_at,
        "failed_ping": failed_ping,
        "control_ping": control_ping,
        "collection_duration_s": collection_s,
        "report_duration_s": report_s,
        "correlation": correlation,
        "report": report,
        "recovery_verified": True,
    }


# --------------------------------------------------
# S04-F03 TEST MATRIX ROW
# --------------------------------------------------

def build_s04_f03_matrix_row(result):
    if result.get("run_id") != "S04-F03":
        raise ValueError("Unexpected run ID")

    correlation = result["correlation"]

    if correlation["assessment"] != "not_initial_trigger":
        raise RuntimeError(
            "Unexpected correlation assessment"
        )

    if (
        correlation["network_impact"]["status"]
        != "potential_impact"
    ):
        raise RuntimeError(
            "Expected potential network impact"
        )

    if (
        correlation["timing"]["status"]
        != "after_first_observation"
    ):
        raise RuntimeError(
            "Change timing was not confirmed"
        )

    if result["recovery_verified"] is not True:
        raise RuntimeError(
            "Recovery was not verified"
        )

    before = result["before_snapshot"]
    after = result["after_snapshot"]

    if (
        before.get("name") != "sw1p1"
        or after.get("name") != "sw1p1"
        or before.get("mode") != "trunk"
        or after.get("mode") != "trunk"
        or set(before.get("vlans", [])) != {10, 20}
        or set(after.get("vlans", [])) != {20}
    ):
        raise RuntimeError(
            "Unexpected sw1p1 configuration change"
        )

    if result["failed_ping"]["packet_loss_pct"] != 100.0:
        raise RuntimeError(
            "VLAN 10 outage was not confirmed"
        )

    if result["control_ping"]["packet_loss_pct"] != 0.0:
        raise RuntimeError(
            "VLAN 20 control failed"
        )

    # Require evidence for both affected ports.
    for device, port in (
        ("sw1", "sw1p1"),
        ("sw2", "sw2p1"),
    ):
        fault_checks = [
            check
            for check in result["report"]["checks"]
            if (
                check.get("device") == device
                and check.get("component") == port
                and check.get("status") == "fault_detected"
                and isinstance(check.get("evidence"), dict)
                and 10 in check["evidence"].get(
                    "missing_vlans", []
                )
            )
        ]

        if len(fault_checks) != 1:
            raise RuntimeError(
                f"Expected fault evidence missing: {port}"
            )

        fault_ids = [
            source["record_id"]
            for check in fault_checks
            for source in check.get("evidence_sources", [])
            if source.get("record_id") is not None
        ]

        if not fault_ids:
            raise RuntimeError(
                f"No evidence record IDs for {port}"
            )

    evidence_ids = [
        str(source["record_id"])
        for check in result["report"]["checks"]
        for source in check.get("evidence_sources", [])
        if source.get("record_id") is not None
    ]

    return {
        "run_id": "S04-F03",
        "scenario": "configuration_change_correlation",
        "variation": "sw2p1_fault_before_sw1p1_change",
        "expected_state": "faulty",
        "expected_fault_class": "missing_vlan_from_trunk",
        "expected_root_cause": "specific_cause_not_scored",
        "observed_status": "fault_detected",
        "observed_fault_class": "missing_vlan_from_trunk",
        "observed_root_cause": "unconfirmed",
        "detection_correct": "true",
        "diagnosis_correct": "not_applicable",
        "false_alarm": "false",
        "collection_status": "success",
        "evidence_record_ids": ";".join(
            dict.fromkeys(evidence_ids)
        ),
        "fault_injected_at_utc": "",
        "first_detected_at_utc": "",
        "diagnosis_completed_at_utc": (
            result["report"]["generated_at"]
        ),
        "collection_duration_s": (
            result["collection_duration_s"]
        ),
        "report_duration_s": (
            result["report_duration_s"]
        ),
        "detection_latency_s": "",
        "diagnosis_latency_s": "",
        "recovery_verified": "true",
        "notes": (
            "Expected correlation: not_initial_trigger; "
            f"observed: {correlation['assessment']}; "
            "initial VLAN 10 fault injected on sw2p1; "
            "HR connectivity failure observed before sw1p1 change; "
            "VLAN 10 subsequently removed from sw1p1; "
            f"first observed failure: {result['first_observed_at']}; "
            f"sw1p1 snapshot window: {result['before_time']} to "
            f"{result['after_time']}; "
            "both modified ports restored; "
            "correlation does not establish causation; "
            "automatic detection latency not measured"
        ),
        "test_case_id": "S04-F03",
        "run_result": "passed",
    }

# --------------------------------------------------
# S04-F04: NO-CONFIGURATION-CHANGE CONTROL
# --------------------------------------------------

def run_s04_f04():
    with protected_trunk_changes() as change:

        # Verify the expected healthy trunk baseline.
        for port in ("sw1p1", "sw2p1"):
            snapshot, _ = capture_port_snapshot(port)

            if (
                snapshot["mode"] != "trunk"
                or set(snapshot["vlans"]) != {10, 20}
            ):
                raise RuntimeError(
                    f"Unexpected baseline on {port}"
                )

        # Capture the control port BEFORE the incident.
        before, before_time = capture_port_snapshot(
            "sw1p1"
        )

        # Inject the real VLAN 10 fault on sw2p1 only.
        change("sw2p1", [20])

        # Verify that VLAN 10 connectivity is interrupted.
        failed_ping = ping(
            "hr1",
            "192.168.10.12",
        )

        first_observed_at = utc_now()

        # VLAN 20 must remain unaffected.
        control_ping = ping(
            "it1",
            "192.168.20.12",
        )

        if failed_ping["packet_loss_pct"] != 100.0:
            raise RuntimeError(
                "Expected VLAN 10 outage not observed"
            )

        if control_ping["packet_loss_pct"] != 0.0:
            raise RuntimeError(
                "VLAN 20 control connectivity failed"
            )

        # Capture sw1p1 AFTER incident observation.
        # Do not modify sw1p1.
        after, after_time = capture_port_snapshot(
            "sw1p1"
        )

        # The control port must remain unchanged.
        if before != after:
            raise RuntimeError(
                "No-change control port was modified"
            )

        # Collect real diagnosis evidence.
        report, collection_s, report_s = (
            collect_and_diagnose()
        )

        if report["summary"]["total_checks"] != 12:
            raise RuntimeError(
                "Incomplete diagnosis report"
            )

        # Require evidence of the actual sw2p1 fault.
        confirmed_fault = any(
            check.get("device") == "sw2"
            and check.get("component") == "sw2p1"
            and check.get("status") == "fault_detected"
            and isinstance(check.get("evidence"), dict)
            and 10 in check["evidence"].get(
                "missing_vlans", []
            )
            for check in report["checks"]
        )

        if not confirmed_fault:
            raise RuntimeError(
                "Real sw2p1 VLAN 10 fault not confirmed"
            )

        # sw1p1 must be reported as healthy.
        control_port_healthy = any(
            check.get("device") == "sw1"
            and check.get("component") == "sw1p1"
            and check.get("status") == "healthy"
            for check in report["checks"]
        )

        if not control_port_healthy:
            raise RuntimeError(
                "No-change control port is not healthy"
            )

        # Correlate the incident with unchanged sw1p1.
        correlation = attach_s04_correlation(
            report,
            "S04-F04",
            before,
            after,
            before_time,
            after_time,
            first_observed_at,
            failed_ping,
        )

        if (
            correlation["configuration_change"]["changed"]
            is not False
        ):
            raise RuntimeError(
                "Unexpected configuration change detected"
            )

        if (
            correlation["network_impact"]["status"]
            != "no_change"
        ):
            raise RuntimeError(
                "Unexpected network impact assessment"
            )

        if (
            correlation["assessment"]
            != "no_change_detected"
        ):
            raise RuntimeError(
                "Unexpected correlation assessment"
            )

    # The protected context restores sw2p1 and
    # verifies network health before returning.
    return {
        "run_id": "S04-F04",
        "before_snapshot": before,
        "after_snapshot": after,
        "before_time": before_time,
        "after_time": after_time,
        "first_observed_at": first_observed_at,
        "failed_ping": failed_ping,
        "control_ping": control_ping,
        "collection_duration_s": collection_s,
        "report_duration_s": report_s,
        "correlation": correlation,
        "report": report,
        "recovery_verified": True,
    }
# --------------------------------------------------
# S04-F04 TEST MATRIX ROW
# --------------------------------------------------

def build_s04_f04_matrix_row(result):
    if result.get("run_id") != "S04-F04":
        raise ValueError("Unexpected run ID")

    correlation = result["correlation"]

    if correlation["assessment"] != "no_change_detected":
        raise RuntimeError(
            "Unexpected correlation assessment"
        )

    if (
        correlation["configuration_change"]["changed"]
        is not False
    ):
        raise RuntimeError(
            "Unexpected configuration change"
        )

    if (
        correlation["network_impact"]["status"]
        != "no_change"
    ):
        raise RuntimeError(
            "Expected no-change impact assessment"
        )

    if result["recovery_verified"] is not True:
        raise RuntimeError(
            "Recovery was not verified"
        )

    before = result["before_snapshot"]
    after = result["after_snapshot"]

    if (
        before.get("name") != "sw1p1"
        or after.get("name") != "sw1p1"
        or before.get("mode") != "trunk"
        or after.get("mode") != "trunk"
        or set(before.get("vlans", [])) != {10, 20}
        or set(after.get("vlans", [])) != {10, 20}
        or before != after
    ):
        raise RuntimeError(
            "Unexpected no-change control snapshots"
        )

    if result["failed_ping"]["packet_loss_pct"] != 100.0:
        raise RuntimeError(
            "VLAN 10 outage was not confirmed"
        )

    if result["control_ping"]["packet_loss_pct"] != 0.0:
        raise RuntimeError(
            "VLAN 20 control failed"
        )

    # The actual fault must be on sw2p1.
    fault_checks = [
        check
        for check in result["report"]["checks"]
        if (
            check.get("device") == "sw2"
            and check.get("component") == "sw2p1"
            and check.get("status") == "fault_detected"
            and isinstance(check.get("evidence"), dict)
            and 10 in check["evidence"].get(
                "missing_vlans", []
            )
        )
    ]

    if len(fault_checks) != 1:
        raise RuntimeError(
            "Expected sw2p1 fault evidence not found"
        )

    fault_record_ids = [
        source["record_id"]
        for check in fault_checks
        for source in check.get("evidence_sources", [])
        if source.get("record_id") is not None
    ]

    if not fault_record_ids:
        raise RuntimeError(
            "No evidence record IDs for sw2p1 fault"
        )

    # The control port must have healthy evidence.
    healthy_control_checks = [
        check
        for check in result["report"]["checks"]
        if (
            check.get("device") == "sw1"
            and check.get("component") == "sw1p1"
            and check.get("status") == "healthy"
        )
    ]

    if len(healthy_control_checks) != 1:
        raise RuntimeError(
            "Healthy sw1p1 control evidence not found"
        )

    control_record_ids = [
        source["record_id"]
        for check in healthy_control_checks
        for source in check.get("evidence_sources", [])
        if source.get("record_id") is not None
    ]

    if not control_record_ids:
        raise RuntimeError(
            "No evidence record IDs for sw1p1 control"
        )

    evidence_ids = [
        str(source["record_id"])
        for check in result["report"]["checks"]
        for source in check.get("evidence_sources", [])
        if source.get("record_id") is not None
    ]

    return {
        "run_id": "S04-F04",
        "scenario": "configuration_change_correlation",
        "variation": "sw2p1_fault_no_change_sw1p1",
        "expected_state": "faulty",
        "expected_fault_class": "missing_vlan_from_trunk",
        "expected_root_cause": "specific_cause_not_scored",
        "observed_status": "fault_detected",
        "observed_fault_class": "missing_vlan_from_trunk",
        "observed_root_cause": "unconfirmed",
        "detection_correct": "true",
        "diagnosis_correct": "not_applicable",
        "false_alarm": "false",
        "collection_status": "success",
        "evidence_record_ids": ";".join(
            dict.fromkeys(evidence_ids)
        ),
        "fault_injected_at_utc": "",
        "first_detected_at_utc": "",
        "diagnosis_completed_at_utc": (
            result["report"]["generated_at"]
        ),
        "collection_duration_s": (
            result["collection_duration_s"]
        ),
        "report_duration_s": (
            result["report_duration_s"]
        ),
        "detection_latency_s": "",
        "diagnosis_latency_s": "",
        "recovery_verified": "true",
        "notes": (
            "Expected correlation: no_change_detected; "
            f"observed: {correlation['assessment']}; "
            "real VLAN 10 fault injected on sw2p1; "
            "sw1p1 configuration remained unchanged; "
            "sw1p1 is on the investigated service path; "
            f"snapshot window: {result['before_time']} to "
            f"{result['after_time']}; "
            f"first observed failure: {result['first_observed_at']}; "
            "no configuration change can be attributed to sw1p1; "
            "correlation does not establish causation; "
            "automatic detection latency not measured"
        ),
        "test_case_id": "S04-F04",
        "run_result": "passed",
    }