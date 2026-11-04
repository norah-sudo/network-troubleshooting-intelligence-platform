
import json
import sqlite3
import subprocess
from datetime import datetime, timezone

from evidence_db import DB_PATH, initialize_database
from ovs_normalization import normalize_ovs_value

# Approved switch ports
SWITCH_PORTS = {
    "sw1": ["sw1p1", "sw1p2", "sw1p3", "sw1p4"],
    "sw2": ["sw2p1", "sw2p2", "sw2p3", "sw2p4"],
}




evidence_records = []

for switch, ports in SWITCH_PORTS.items():
    for port in ports:
        command = f"ovs-vsctl list Port {port}"

        try:
            result = subprocess.run(
                [
                    "sudo", "-n",
                    "ovs-vsctl",
                    "--format=json",
                    "--columns=name,vlan_mode,tag,trunks",
                    "list", "Port", port,
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                status = "failed"
                output = result.stderr
            else:
                data = json.loads(result.stdout)

                if len(data["data"]) != 1:
                    raise ValueError("Expected exactly one port")

                values = dict(zip(data["headings"], data["data"][0]))

                normalized = {
                    key: normalize_ovs_value(values[key], key)
                    for key in ("name", "vlan_mode", "tag", "trunks")
                }

                status = "success"
                output = json.dumps(normalized, sort_keys=True)

        except subprocess.TimeoutExpired:
            status = "timeout"
            output = "OVS command timed out after 10 seconds."

        except (ValueError, KeyError, TypeError) as error:
            status = "failed"
            output = f"Invalid OVS output: {error}"

        evidence_records.append({
            "device": switch,
            "command": command,
            "status": status,
            "output": output,
            "collected_at": datetime.now(timezone.utc).isoformat(),
        })

        print(f"{switch} | {port} | {status}")
        if status != "success":
            print("Error:", output)


# Save evidence to SQLite
initialize_database()

with sqlite3.connect(DB_PATH) as connection:
    connection.executemany(
        """
        INSERT INTO evidence_records
        (device, command, status, output, collected_at)
        VALUES (:device, :command, :status, :output, :collected_at)
        """,
        evidence_records,
    )

print("Switch evidence saved:", len(evidence_records))

# Check switch collection results
failed_records = [
    record for record in evidence_records
    if record["status"] != "success"
]

if failed_records:
    print("WARNING:", len(failed_records), "switch collections failed.")
    raise SystemExit(1)

print("Switch collection completed successfully.")
