
import json
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone

from diagnosis_engine import diagnose_routers, diagnose_switches
from evidence_db import DB_PATH
from evidence_provenance import get_check_provenance
from state_monitor import BASELINE_PATH


def make_check(device, component, diagnosis):
    return {
        "device": device,
        "component": component,
        "status": diagnosis["status"],
        "issue": diagnosis.get("issue"),
        "evidence": diagnosis.get("evidence"),
        "differences": diagnosis.get("differences", []),
        "syslog_evidence": diagnosis.get("syslog_evidence", []),
        "possible_cause": diagnosis.get("possible_cause"),
        "recommendation": diagnosis.get("recommendation"),
    }


def build_report(routers, switches):
    checks = []

    # Router diagnosis results
    for router in routers:
        for component in ("interface", "ospf"):
            checks.append(
                make_check(
                    router["device"],
                    component,
                    router[component],
                )
            )

    # Switch diagnosis results
    for switch in switches:
        checks.append(
            make_check(
                switch["switch"],
                switch["port"],
                switch["diagnosis"],
            )
        )

    counts = Counter(
        check["status"] for check in checks
    )

    return {
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "summary": {
            "total_checks": len(checks),
            "healthy": counts["healthy"],
            "other_findings": (
                len(checks) - counts["healthy"]
            ),
            "statuses": dict(counts),
        },
        "checks": checks,
    }



def print_report(report):
    print("\n=== NETWORK DIAGNOSIS REPORT ===")

    summary = report["summary"]

    print("Generated at:", report["generated_at"])
    print("Total checks:", summary["total_checks"])
    print("Healthy:", summary["healthy"])
    print("Other findings:", summary["other_findings"])

    print("\n=== DEVICE RESULTS ===")

    for check in report["checks"]:
        print(
            f"\n{check['device']} / "
            f"{check['component']}: "
            f"{check['status']}"
        )

        sources = check.get("evidence_sources", [])

        if sources:
            print("  Evidence sources:")

            for source in sources:
                print("    Record ID:", source["record_id"])
                print("    Command:", source["command"])
                print(
                    "    Collection status:",
                    source["collection_status"]
                )
                print(
                    "    Collected at:",
                    source["collected_at"]
                )
                print(
                    "    Freshness:",
                    source["freshness"]
                )

        if check["status"] == "healthy":
            continue

        for field in (
            "issue",
            "evidence",
            "differences",
            "syslog_evidence",
            "possible_cause",
            "recommendation",
        ):
            value = check.get(field)

            if value:
                if isinstance(value, (dict, list)):
                    value = json.dumps(
                        value,
                        ensure_ascii=False,
                    )

                print(f"  {field}: {value}")

    # Show incident correlation only when attached.
    correlations = report.get(
        "incident_correlations", []
    )

    if correlations:
        print("\n=== INCIDENT CORRELATION ===")

        for entry in correlations:
            correlation = entry["correlation"]

            change = correlation["configuration_change"]
            impact = correlation["network_impact"]
            timing = correlation["timing"]

            print("\nIncident ID:", entry["incident_id"])
            print("Source:", entry["source_type"])
            print("Change detected:", change["changed"])
            print("Network impact:", impact["status"])
            print("Timing:", timing["status"])
            print(
                "Assessment:",
                correlation["assessment"]
            )
            print(
                "Conclusion:",
                correlation["conclusion"]
            )

            if entry["source_type"] == "simulation":
                print(
                    "Note: Simulated incident, "
                    "not a real network fault."
                )



def main():
    # Load expected healthy network state.
    with BASELINE_PATH.open(
        encoding="utf-8"
    ) as file:
        baseline = json.load(file)

    # Open the evidence database in read-only mode.
    with closing(
        sqlite3.connect(
            f"file:{DB_PATH}?mode=ro",
            uri=True,
        )
    ) as db:

        # Use one consistent database snapshot.
        db.execute("BEGIN")

        # Run the existing diagnosis engines.
        routers = diagnose_routers(
            db, baseline
        )

        switches = diagnose_switches(
            db, baseline
        )

        # Build the unified diagnosis report.
        report = build_report(
            routers, switches
        )

        # Attach evidence provenance to every check.
        for check in report["checks"]:
            check["evidence_sources"] = (
                get_check_provenance(
                    db,
                    baseline,
                    check["device"],
                    check["component"],
                )
            )

    # Display the final report.
    print_report(report)

    return report


if __name__ == "__main__":
    main()
