
import sqlite3
import subprocess
from pathlib import Path
from datetime import datetime, timezone

from evidence_db import DB_PATH, initialize_database


# Approved network devices
DEVICES = [
    "clab-ospftest-r1",
    "clab-ospftest-r2",
]

# Approved read-only commands
COMMANDS = [
    "show ip ospf neighbor",
    "show interface eth1",
]

# Trusted SSH host keys
KNOWN_HOSTS = Path.home() / ".ssh" / "clab_known_hosts"
# Dedicated key for the restricted SSH collector
COLLECTOR_KEY = (
    Path.home()
    / ".local"
    / "share"
    / "network-troubleshooting-platform"
    / "collector_ed25519"
)

# Store collected evidence in memory
evidence_records = []


# Step 1: Collect network evidence
for device in DEVICES:
    for command in COMMANDS:

        print("=" * 50)
        print("Device:", device)
        print("Collected at:", datetime.now(timezone.utc).isoformat())
        print("Command:", command)
        print("-" * 50)

        try:
            result = subprocess.run(
                [
    "ssh",
    "-i", str(COLLECTOR_KEY),
    "-o", "IdentitiesOnly=yes",
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=8",
    "-o", f"UserKnownHostsFile={KNOWN_HOSTS}",
    "-o", "StrictHostKeyChecking=yes",
    f"collector@{device}",
    command,
],
                capture_output=True,
                text=True,
                timeout=15,
            )

            if result.returncode == 0:
                status = "success"
                output = result.stdout
                print(output)

            else:
                status = "failed"
                output = result.stderr
                print("SSH failed:", output)

        except subprocess.TimeoutExpired:
            status = "timeout"
            output = "SSH command timed out after 15 seconds."
            print("ERROR:", output)

        except OSError as error:
            status = "failed"
            output = str(error)
            print("SSH execution failed:", output)

        # Record the collection result
        evidence_records.append({
            "device": device,
            "command": command,
            "status": status,
            "output": output,
            "collected_at": datetime.now(timezone.utc).isoformat(),
        })


# Step 2: Display evidence summary
print("\nTotal evidence records:", len(evidence_records))

for record in evidence_records:
    print(
        record["device"],
        "|",
        record["command"],
        "|",
        record["status"],
    )


# Step 3: Save evidence to SQLite
initialize_database()

connection = sqlite3.connect(DB_PATH)

try:
    connection.executemany(
        """
        INSERT INTO evidence_records
        (device, command, status, output, collected_at)
        VALUES (:device, :command, :status, :output, :collected_at)
        """,
        evidence_records,
    )

    connection.commit()

finally:
    connection.close()

print("Saved to SQLite:", len(evidence_records), "records")


# Step 4: Check collection results
failed_records = [
    record for record in evidence_records
    if record["status"] != "success"
]

if failed_records:
    print(
        "WARNING:",
        len(failed_records),
        "collections failed or timed out."
    )
    raise SystemExit(1)

print("SSH collection completed successfully.")
