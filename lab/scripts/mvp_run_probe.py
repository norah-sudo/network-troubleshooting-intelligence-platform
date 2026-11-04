import io
import subprocess
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path

from diagnosis_report import main as generate_report


SCRIPTS_DIR = Path(__file__).resolve().parent


def main():
    # Measure collection execution time.
    start = time.perf_counter()

    collection = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "collect_all.py")],
        capture_output=True,
        text=True,
        check=False,
    )

    collection_duration = time.perf_counter() - start

    print("=== MVP MEASUREMENT PROBE ===")
    print("Collection exit code:", collection.returncode)
    print("Collection duration:", round(collection_duration, 4), "s")

    if collection.returncode != 0:
        print("Collection failed. Diagnosis not scored.")
        print(collection.stdout[-2000:])
        print(collection.stderr[-1000:])
        raise SystemExit(1)

    # Measure report execution using freshly collected evidence.
    start = time.perf_counter()

    with redirect_stdout(io.StringIO()):
        report = generate_report()

    report_duration = time.perf_counter() - start

    print("Report duration:", round(report_duration, 4), "s")
    print("Total checks:", report["summary"]["total_checks"])
    print("Healthy:", report["summary"]["healthy"])
    print("Other findings:", report["summary"]["other_findings"])

    print("\n=== CHECK RESULTS ===")

    for check in report["checks"]:
        sources = check.get("evidence_sources", [])
        record_ids = [
            source.get("record_id")
            for source in sources
            if source.get("record_id") is not None
        ]

        print(
            f"{check['device']} / {check['component']}: "
            f"{check['status']} | Evidence IDs: {record_ids}"
        )

    print("\nDetection latency: NOT MEASURED")
    print("Diagnosis latency from fault onset: NOT MEASURED")
    print("Test Matrix: NO ROW ADDED")


if __name__ == "__main__":
    main()
