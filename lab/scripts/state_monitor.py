
import json
import sqlite3
from datetime import datetime, timezone
from collections import Counter
from contextlib import closing
from pathlib import Path

from evidence_db import DB_PATH
from evidence_parser import (
    parse_interface,
    parse_ospf_neighbors,
    parse_switch_port,
)
from state_comparator import compare_state


BASELINE_PATH = (
    Path(__file__).resolve().parent.parent
    / "configs" / "healthy_baseline.json"
)



MAX_EVIDENCE_AGE_SECONDS = 600  # 10 minutes


def latest_output(db, device, command):
    row = db.execute(
        """
        SELECT status, output, collected_at
        FROM evidence_records
        WHERE device = ? AND command = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (device, command),
    ).fetchone()

    if not row or row[0] != "success":
        return None

    try:
        collected_at = datetime.fromisoformat(row[2])

        if collected_at.tzinfo is None:
            return None

        age_seconds = (
            datetime.now(timezone.utc) - collected_at
        ).total_seconds()

    except (ValueError, TypeError):
        return None

    # Reject old evidence or suspicious future timestamps
    if age_seconds > MAX_EVIDENCE_AGE_SECONDS or age_seconds < -30:
        return None

    return row[1]



def display_result(label, expected, observed):
    result = compare_state(expected, observed)

    print(label, "=>", result["status"].upper())

    for difference in result["differences"]:
        print(
            "  Changed:", difference["field"],
            "| Expected:", difference["expected"],
            "| Observed:", difference["observed"],
        )

    return result["status"]


def check_router(db, device, expected):
    interface_output = latest_output(
        db, device, "show interface eth1"
    )
    ospf_output = latest_output(
        db, device, "show ip ospf neighbor"
    )

    observed = None

    if interface_output is not None and ospf_output is not None:
        try:
            interface = parse_interface(interface_output)
            neighbors = parse_ospf_neighbors(ospf_output)

            if interface["interface"] != expected["interface"]:
                raise ValueError("Unexpected interface name")

            neighbor = next(
                (
                    item for item in neighbors
                    if item["neighbor_id"]
                    == expected["ospf_neighbor_id"]
                ),
                None,
            )

            observed = {
                **interface,
                "ospf_neighbor_id": (
                    neighbor["neighbor_id"] if neighbor else None
                ),
                "ospf_state": (
                    neighbor["state"] if neighbor else None
                ),
            }

        except (ValueError, TypeError, KeyError) as error:
            print(device, "| Parsing error:", error)

    return display_result(device, expected, observed)


def check_switch_port(db, switch, port, expected):
    command = f"ovs-vsctl list Port {port}"
    output = latest_output(db, switch, command)

    observed = None

    if output is not None:
        try:
            parsed = parse_switch_port(output)

            if parsed["name"] != port:
                raise ValueError("Unexpected port name")

            observed = {
                key: value
                for key, value in parsed.items()
                if key != "name"
            }

        except (ValueError, TypeError, KeyError) as error:
            print(port, "| Parsing error:", error)

    return display_result(port, expected, observed)


def main():
    with BASELINE_PATH.open(encoding="utf-8") as file:
        baseline = json.load(file)

    results = []

    with closing(
        sqlite3.connect(
            f"file:{DB_PATH}?mode=ro",
            uri=True,
        )
    ) as db:

        print("\n=== Router State ===")

        for device, expected in baseline["routers"].items():
            results.append(
                check_router(db, device, expected)
            )

        print("\n=== Switch State ===")

        for switch, ports in baseline["switches"].items():
            for port, expected in ports.items():
                results.append(
                    check_switch_port(db, switch, port, expected)
                )

    counts = Counter(results)

    print("\n=== State Comparison Summary ===")
    print("MATCH:", counts["match"])
    print("MISMATCH:", counts["mismatch"])
    print(
        "INSUFFICIENT EVIDENCE:",
        counts["insufficient_evidence"],
    )

    if any(status != "match" for status in results):
        raise SystemExit(1)

    print("\nAll monitored states match the baseline.")


if __name__ == "__main__":
    main()
