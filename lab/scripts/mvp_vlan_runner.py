import argparse
import csv
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time

from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from diagnosis_report import main as generate_report


ROOT = Path(__file__).resolve().parents[2]

MATRIX = ROOT / "lab/docs/MVP_TEST_MATRIX.csv"
PLAN = ROOT / "lab/docs/MVP_TEST_PLAN.md"
LOG_DIR = ROOT / "lab/logs"

PORTS = ("sw1p1", "sw2p1")

REQUIRED_MATRIX_COLUMNS = {
    "run_id",
    "test_case_id",
    "run_result",
    "failure_stage",
    "on_demand_response_s",
}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def command(args, timeout=90, allow_failure=False):
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )

    if result.returncode != 0 and not allow_failure:
        raise RuntimeError(
            f"Command failed: {args}\n"
            f"{result.stdout[-500:]}\n"
            f"{result.stderr[-500:]}"
        )

    return result


def get_trunks(port):
    result = command([
        "sudo", "-n", "ovs-vsctl",
        "get", "Port", port, "trunks",
    ])

    return result.stdout.strip().replace(" ", "")


def set_trunks(port, vlans):
    command([
        "sudo", "-n", "ovs-vsctl", "set",
        "Port", port, "vlan_mode=trunk",
        f"trunks={','.join(map(str, vlans))}",
    ])


def ping(host, destination):
    result = command([
        "docker", "exec", f"clab-ospftest-{host}",
        "ping", "-c", "3", "-W", "1", destination,
    ], timeout=20, allow_failure=True)

    match = re.search(
        r"(\d+(?:\.\d+)?)% packet loss",
        result.stdout,
    )

    if not match or result.returncode not in (0, 1):
        raise RuntimeError("Invalid ping evidence")

    return {
        "source": host,
        "destination": destination,
        "packet_loss_pct": float(match.group(1)),
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def check_connectivity():
    return {
        "vlan10": ping("hr1", "192.168.10.12"),
        "vlan20": ping("it1", "192.168.20.12"),
    }


def collect_and_diagnose():
    start = time.perf_counter()

    command([
        sys.executable,
        str(ROOT / "lab/scripts/collect_all.py"),
    ])

    collection_duration = time.perf_counter() - start

    start = time.perf_counter()

    with redirect_stdout(io.StringIO()):
        diagnosis = generate_report()

    report_duration = time.perf_counter() - start

    return (
        diagnosis,
        round(collection_duration, 4),
        round(report_duration, 4),
    )


def verify_healthy():
    for port in PORTS:
        if get_trunks(port) != "[10,20]":
            raise RuntimeError(
                f"Unhealthy trunk: {port}"
            )

    pings = check_connectivity()

    if any(
        info["packet_loss_pct"] != 0
        for info in pings.values()
    ):
        raise RuntimeError(
            "Healthy connectivity verification failed"
        )

    diagnosis, _, _ = collect_and_diagnose()
    summary = diagnosis["summary"]

    if (
        summary["total_checks"] != 12
        or summary["healthy"] != 12
        or summary["other_findings"] != 0
    ):
        raise RuntimeError(
            f"Unhealthy baseline: {summary}"
        )


# --------------------------------------------------
# CSV RESULT RECORDING
# --------------------------------------------------

def csv_bool(value):
    if value is None:
        return "not_applicable"

    return "true" if value else "false"


def build_matrix_row(result):
    run_id = result["run_id"]
    test_case_id = result.get("test_case_id", run_id)

    port = result["port"]
    missing_vlan = result["missing_vlan"]

    observed_status = result.get("observed_status", "")

    missing_vlans = result.get("missing_vlans") or []

    if observed_status == "fault_detected":
        detection_correct = "true"
    elif observed_status:
        detection_correct = "false"
    else:
        detection_correct = "not_applicable"

    observed_fault_class = ""
    observed_root_cause = ""

    if (
        observed_status == "fault_detected"
        and missing_vlans
    ):
        observed_fault_class = "missing_vlan_from_trunk"
        observed_root_cause = (
            f"VLAN {','.join(map(str, missing_vlans))} "
            f"missing from {port} trunk"
        )

    notes = [
        "On-demand response is not automatic "
        "detection latency."
    ]

    if result["result"] == "blocked":
        notes.append(
            "Preflight blocked the run before fault injection."
        )

    pings = result.get("ping_evidence") or {}

    for vlan, info in pings.items():
        notes.append(
            f"{vlan} loss={info['packet_loss_pct']}%"
        )

    if result.get("error"):
        notes.append(
            f"Error: {result['error']}"
        )

    if result.get("recovery_error"):
        notes.append(
            f"Recovery error: {result['recovery_error']}"
        )

    recovery = result.get("recovery_verified")

    if recovery is None:
        recovery_text = "not_required"
    else:
        recovery_text = csv_bool(recovery)

    evidence_ids = result.get("evidence_record_ids") or []

    row = {
        "run_id": run_id,
        "scenario": "missing_vlan_from_trunk",
        "variation": (
            f"remove_vlan{missing_vlan}_{port}"
        ),
        "expected_state": "faulty",
        "expected_fault_class": "missing_vlan_from_trunk",
        "expected_root_cause": (
            f"VLAN {missing_vlan} removed from {port} trunk"
        ),
        "observed_status": (
            observed_status
            or ("blocked" if result["result"] == "blocked" else "")
        ),
        "observed_fault_class": observed_fault_class,
        "observed_root_cause": observed_root_cause,
        "detection_correct": detection_correct,
        "diagnosis_correct": csv_bool(
            result.get("diagnosis_correct")
        ),
        "false_alarm": "not_applicable",
        "collection_status": result.get(
            "collection_status", "not_started"
        ),
        "evidence_record_ids": ";".join(
            str(record_id)
            for record_id in evidence_ids
        ),

        # Exact fault onset and automatic detection
        # timestamps were not measured.
        "fault_injected_at_utc": "",
        "first_detected_at_utc": "",

        "diagnosis_completed_at_utc": result.get(
            "diagnosis_completed_at_utc", ""
        ),
        "collection_duration_s": result.get(
            "collection_duration_s", ""
        ),
        "report_duration_s": result.get(
            "report_duration_s", ""
        ),
        "detection_latency_s": "",
        "diagnosis_latency_s": "",
        "recovery_verified": recovery_text,
        "notes": "; ".join(notes),
        "test_case_id": test_case_id,
        "run_result": result["result"],
        "failure_stage": result.get("failure_stage", ""),
        "on_demand_response_s": result.get(
            "on_demand_response_s", ""
        ),
    }

    return row


def append_matrix_result(result, row_builder=build_matrix_row):
    with MATRIX.open(
        newline="",
        encoding="utf-8",
    ) as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames
        rows = list(reader)

    if not columns:
        raise RuntimeError(
            "Test matrix has no CSV header"
        )

    missing = REQUIRED_MATRIX_COLUMNS - set(columns)

    if missing:
        raise RuntimeError(
            f"Missing test matrix columns: {sorted(missing)}"
        )

    if any(
        row["run_id"] == result["run_id"]
        for row in rows
    ):
        raise RuntimeError(
            f"Run already recorded: {result['run_id']}"
        )

    new_row = row_builder(result)

    # Preserve the existing line-ending style.
    original_bytes = MATRIX.read_bytes()

    line_ending = (
        "\r\n"
        if b"\r\n" in original_bytes
        else "\n"
    )

    temporary_path = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=MATRIX.parent,
            prefix=".mvp_matrix_",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)

            writer = csv.DictWriter(
                temporary,
                fieldnames=columns,
                lineterminator=line_ending,
            )

            writer.writeheader()
            writer.writerows(rows)

            writer.writerow({
                name: new_row.get(name, "")
                for name in columns
            })

            temporary.flush()
            os.fsync(temporary.fileno())

        os.chmod(
            temporary_path,
            MATRIX.stat().st_mode & 0o777,
        )

        os.replace(
            temporary_path,
            MATRIX,
        )

    finally:
        if (
            temporary_path is not None
            and temporary_path.exists()
        ):
            temporary_path.unlink()


# --------------------------------------------------
# JSON + CSV RESULT SAVING
# --------------------------------------------------

def save_result(result, log):
    LOG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    # Exclusive creation protects existing JSON.
    with log.open(
        "x",
        encoding="utf-8",
    ) as f:
        json.dump(
            result,
            f,
            indent=2,
        )
        f.write("\n")

    print("Result saved:", log)

    try:
        append_matrix_result(result)

    except Exception as error:
        print(
            "ERROR: JSON saved, but CSV registration failed.",
            flush=True,
        )

        print(
            "CSV ERROR:", error,
            flush=True,
        )

        print(
            "Use --reconcile to register this JSON "
            "without repeating the fault.",
            flush=True,
        )

        raise SystemExit(1)

    print("Test Matrix: ROW ADDED")


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--run-id",
        required=True,
    )

    parser.add_argument(
        "--port",
        choices=PORTS,
    )

    parser.add_argument(
        "--missing-vlan",
        type=int,
        choices=(10, 20),
    )

    parser.add_argument(
        "--execute",
        action="store_true",
    )

    parser.add_argument(
        "--reconcile",
        action="store_true",
        help=(
            "Register an existing JSON result in CSV "
            "without network operations."
        ),
    )

    args = parser.parse_args()

    match = re.fullmatch(
        r"(S01-F\d{2,3})(?:-A\d{2})?",
        args.run_id,
    )

    if not match:
        raise SystemExit(
            "Invalid S01 fault run ID"
        )

    test_case_id = match.group(1)

    log = LOG_DIR / f"{args.run_id}_result.json"

    # Reconciliation never touches the network.
    if args.reconcile:
        if not log.exists():
            raise SystemExit(
                "STOP: No JSON result to reconcile"
            )

        result = json.loads(
            log.read_text(encoding="utf-8")
        )

        if result.get("run_id") != args.run_id:
            raise SystemExit(
                "STOP: JSON run ID mismatch"
            )

        append_matrix_result(result)

        print(
            "Reconciliation completed:",
            args.run_id,
        )

        return

    if args.port is None:
        parser.error("--port is required")

    if args.missing_vlan is None:
        parser.error("--missing-vlan is required")

    with MATRIX.open(
        newline="",
        encoding="utf-8",
    ) as f:
        runs = list(csv.DictReader(f))

    if any(
        row["run_id"] == args.run_id
        for row in runs
    ):
        raise SystemExit(
            "STOP: Run already recorded"
        )

    if test_case_id not in PLAN.read_text(
        encoding="utf-8"
    ):
        raise SystemExit(
            "STOP: Define the run in the shared plan first"
        )

    if log.exists():
        raise SystemExit(
            "STOP: Result log already exists"
        )

    result = {
        "run_id": args.run_id,
        "test_case_id": test_case_id,
        "port": args.port,
        "missing_vlan": args.missing_vlan,
        "started_at_utc": utc_now(),
        "result": "blocked",
        "failure_stage": "",
        "recovery_verified": None,
        "collection_status": "not_started",
        "detection_latency_s": None,
        "diagnosis_latency_s": None,
        "timing_note": (
            "On-demand response, not automatic "
            "detection latency."
        ),
    }

    # ----------------------------------------------
    # PREFLIGHT
    # ----------------------------------------------

    print(
        "Checking healthy baseline...",
        flush=True,
    )

    try:
        verify_healthy()

    except (Exception, KeyboardInterrupt) as error:
        print(
            "PREFLIGHT ERROR:",
            error,
            flush=True,
        )

        if args.execute:
            result["result"] = "blocked"
            result["failure_stage"] = "preflight"
            result["error"] = str(error)

            save_result(result, log)

        raise SystemExit(1)

    print("PASS: Healthy baseline")

    if not args.execute:
        print(
            "DRY RUN PASSED — No fault injected."
        )
        return

    # ----------------------------------------------
    # FAULT EXECUTION
    # ----------------------------------------------

    result["result"] = "failed"
    result["recovery_verified"] = False

    injection_attempted = False
    current_stage = "fault_injection"

    try:
        injection_attempted = True

        remaining = sorted(
            {10, 20} - {args.missing_vlan}
        )

        set_trunks(
            args.port,
            remaining,
        )

        current_stage = "fault_verification"

        expected = f"[{remaining[0]}]"

        if get_trunks(args.port) != expected:
            raise RuntimeError(
                "Fault injection not confirmed"
            )

        other_port = next(
            port
            for port in PORTS
            if port != args.port
        )

        if get_trunks(other_port) != "[10,20]":
            raise RuntimeError(
                "Unexpected change on the control port"
            )

        result[
            "fault_configuration_verified_at_utc"
        ] = utc_now()

        print(
            "PASS: Fault configuration verified",
            flush=True,
        )

        # ------------------------------------------
        # CONNECTIVITY
        # ------------------------------------------

        current_stage = "connectivity"

        pings = check_connectivity()
        result["ping_evidence"] = pings

        for vlan, info in pings.items():
            expected_loss = (
                100
                if int(vlan[-2:]) == args.missing_vlan
                else 0
            )

            if info["packet_loss_pct"] != expected_loss:
                raise RuntimeError(
                    f"Unexpected connectivity: {vlan}"
                )

        print(
            "PASS: Fault and control connectivity verified"
        )

        result["fault_verified_at_utc"] = utc_now()

        # ------------------------------------------
        # COLLECTION
        # ------------------------------------------

        current_stage = "collection"
        result["collection_status"] = "in_progress"

        start = time.perf_counter()

        diagnosis, collection_time, report_time = (
            collect_and_diagnose()
        )

        result["collection_status"] = "success"

        result["collection_duration_s"] = (
            collection_time
        )

        result["report_duration_s"] = (
            report_time
        )

        result["on_demand_response_s"] = round(
            time.perf_counter() - start,
            4,
        )

        result[
            "diagnosis_completed_at_utc"
        ] = utc_now()

        result["report_summary"] = (
            diagnosis["summary"]
        )

        # ------------------------------------------
        # DIAGNOSIS
        # ------------------------------------------

        current_stage = "diagnosis"

        switch = args.port[:3]

        target = next(
            check
            for check in diagnosis["checks"]
            if check["device"] == switch
            and check["component"] == args.port
        )

        evidence = target.get("evidence") or {}
        sources = target.get("evidence_sources") or []

        result["observed_status"] = target["status"]

        result["observed_issue"] = target.get(
            "issue"
        )

        result["missing_vlans"] = evidence.get(
            "missing_vlans"
        )

        result["evidence_sources"] = sources

        result["evidence_record_ids"] = [
            source["record_id"]
            for source in sources
            if source.get("record_id") is not None
        ]

        unexpected = [
            {
                "device": check["device"],
                "component": check["component"],
                "status": check["status"],
            }
            for check in diagnosis["checks"]
            if check is not target
            and check["status"] != "healthy"
        ]

        result["unexpected_findings"] = unexpected

        result["detection_correct"] = (
            target["status"] == "fault_detected"
        )

        result["diagnosis_correct"] = (
            len(diagnosis["checks"]) == 12
            and target["status"] == "fault_detected"
            and evidence.get("missing_vlans")
            == [args.missing_vlan]
            and bool(result["evidence_record_ids"])
            and not unexpected
        )

        print("Diagnosis:", target["status"])

        print(
            "Missing VLANs:",
            result["missing_vlans"],
        )

        print(
            "Evidence IDs:",
            result["evidence_record_ids"],
        )

        print(
            "Unexpected findings:",
            unexpected,
        )

        print(
            "Collection:",
            collection_time,
            "s",
        )

        print(
            "Report:",
            report_time,
            "s",
        )

        print(
            "On-demand response:",
            result["on_demand_response_s"],
            "s",
        )

        if not result["diagnosis_correct"]:
            raise RuntimeError(
                "Diagnosis criteria not met"
            )

    except (Exception, KeyboardInterrupt) as error:
        result["error"] = str(error)
        result["failure_stage"] = current_stage

        if current_stage == "collection":
            result["collection_status"] = "failed"

        print(
            "TEST ERROR:",
            error,
            flush=True,
        )

    finally:
        if injection_attempted:
            print(
                "Restoring network...",
                flush=True,
            )

            try:
                # The preflight requires exactly [10,20].
                set_trunks(
                    args.port,
                    [10, 20],
                )

                verify_healthy()

                result["recovery_verified"] = True

            except (Exception, KeyboardInterrupt) as error:
                result["recovery_error"] = str(error)

                if result["failure_stage"]:
                    result["failure_stage"] += "+recovery"
                else:
                    result["failure_stage"] = "recovery"

                print(
                    "RECOVERY ERROR:",
                    error,
                    flush=True,
                )

            print(
                "Recovery verified:",
                result["recovery_verified"],
            )

    # ----------------------------------------------
    # FINAL RESULT
    # ----------------------------------------------

    result["result"] = (
        "passed"
        if result.get("diagnosis_correct") is True
        and result["recovery_verified"] is True
        and "error" not in result
        and "recovery_error" not in result
        else "failed"
    )

    save_result(
        result,
        log,
    )

    print(
        "Test result:",
        result["result"],
    )

    if not result["recovery_verified"]:
        print(
            "WARNING: Manually restore the affected port "
            f"{args.port} to trunks=10,20"
        )

    if result["result"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()