
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent

SCRIPTS = [
    "ssh_collector.py",
    "switch_collector.py",
    "syslog_importer.py",
]

results = {}

# Run all collection programs
for script in SCRIPTS:
    print(f"\n=== Running {script} ===", flush=True)

    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / script)],
            check=False,
        )

        results[script] = result.returncode

    except OSError as error:
        print(f"ERROR running {script}: {error}")
        results[script] = 1


# Display final collection summary
print("\n=== Collection Summary ===")

for script, exit_code in results.items():
    if exit_code == 0:
        print(f"{script}: OK")
    else:
        print(f"{script}: FAILED (exit code {exit_code})")


# Report overall result
if any(code != 0 for code in results.values()):
    print("\nCollection cycle finished with errors.")
    raise SystemExit(1)

print("\nCollection cycle finished successfully.")
