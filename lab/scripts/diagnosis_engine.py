
import json
import sqlite3
from collections import Counter

from evidence_db import DB_PATH
from state_monitor import BASELINE_PATH, latest_output
from evidence_parser import (
    parse_interface,
    parse_ospf_neighbors,
    parse_switch_port,
)
from interface_diagnosis import diagnose_interface
from ospf_diagnosis import diagnose_ospf, diagnose_ospf_with_syslog
from vlan_diagnosis import diagnose_trunk
from state_comparator import compare_state


def safe_parse(output, parser):
    if output is None:
        return None

    try:
        return parser(output)
    except (ValueError, TypeError, KeyError) as error:
        print("  Evidence parsing failed:", error)
        return None


def diagnose_routers(db, baseline):
    reports = []

    for device, expected in baseline["routers"].items():
        interface_command = (
            f"show interface {expected['interface']}"
        )

        interface_output = latest_output(
            db, device, interface_command
        )
        ospf_output = latest_output(
            db, device, "show ip ospf neighbor"
        )

        interface = safe_parse(
            interface_output, parse_interface
        )
        neighbors = safe_parse(
            ospf_output, parse_ospf_neighbors
        )

        interface_report = diagnose_interface(
            device, expected, interface
        )

        ospf_report = diagnose_ospf(
            device, expected, interface, neighbors
        )

        # Correlate Syslog only when OSPF fault is detected
        if (
            ospf_report["status"] == "fault_detected"
            and ospf_output is not None
        ):
            row = db.execute(
                """
                SELECT collected_at
                FROM evidence_records
                WHERE device = ?
                  AND command = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (device, "show ip ospf neighbor"),
            ).fetchone()

            if row:
                ospf_report = diagnose_ospf_with_syslog(
                    db,
                    device,
                    expected,
                    interface,
                    neighbors,
                    row[0],
                )


        reports.append({
            "device": device,
            "interface": interface_report,
            "ospf": ospf_report,
        })

    return reports


def diagnose_switches(db, baseline):
    reports = []

    for switch, ports in baseline["switches"].items():
        for port, expected in ports.items():
            command = f"ovs-vsctl list Port {port}"

            output = latest_output(db, switch, command)
            observed = safe_parse(output, parse_switch_port)

            if expected["mode"] == "trunk":
                result = diagnose_trunk(
                    switch, port, expected, observed
                )

            elif expected["mode"] == "access":
                if (
                    not isinstance(observed, dict)
                    or observed.get("name") != port
                ):
                    result = {
                        "status": "insufficient_evidence",
                        "issue": "Access port evidence unavailable or invalid",
                        "recommendation": "Collect valid port evidence.",
                    }

                else:
                    actual = {
                        "mode": observed.get("mode"),
                        "vlan": observed.get("vlan"),
                    }

                    comparison = compare_state(
                        expected, actual
                    )

                    status_map = {
                        "match": "healthy",
                        "mismatch": "configuration_mismatch",
                        "insufficient_evidence": "insufficient_evidence",
                    }

                    status = status_map[comparison["status"]]

                    result = {
                        "status": status,
                        "issue": (
                            None if status == "healthy"
                            else "Access port differs from baseline"
                        ),
                        "differences": comparison["differences"],
                        "recommendation": (
                            None if status == "healthy"
                            else "Review access port VLAN configuration."
                        ),
                    }

            else:
                result = {
                    "status": "insufficient_evidence",
                    "issue": "Unsupported baseline port mode",
                }

            reports.append({
                "switch": switch,
                "port": port,
                "diagnosis": result,
            })

    return reports


def main():
    with BASELINE_PATH.open(encoding="utf-8") as file:
        baseline = json.load(file)

    with sqlite3.connect(
        f"file:{DB_PATH}?mode=ro", uri=True
    ) as db:
        routers = diagnose_routers(db, baseline)
        switches = diagnose_switches(db, baseline)

    statuses = []

    print("\n=== Unified Router Diagnosis ===")

    for report in routers:
        print("\nDevice:", report["device"])

        for category in ("interface", "ospf"):
            result = report[category]
            status = result["status"]
            statuses.append(status)

            print(f"  {category.upper()}: {status}")

            if result.get("issue"):
                print("  Issue:", result["issue"])

    print("\n=== Unified Switch Diagnosis ===")

    for report in switches:
        result = report["diagnosis"]
        status = result["status"]
        statuses.append(status)

        print(
            f"{report['switch']} / {report['port']}: "
            f"{status}"
        )

        if result.get("issue"):
            print("  Issue:", result["issue"])

        for difference in result.get("differences", []):
            print("  Difference:", difference)

    counts = Counter(statuses)

    print("\n=== Diagnosis Summary ===")
    print("Healthy:", counts["healthy"])
    print("Other findings:", len(statuses) - counts["healthy"])
    print("Total checks:", len(statuses))

    if any(status != "healthy" for status in statuses):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
