import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import mvp_vlan_runner as runner


class TestMVPVLANRunner(unittest.TestCase):

    def setUp(self):
        # Isolated temporary files
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        base = Path(self.temp.name)

        self.matrix = base / "matrix.csv"
        self.plan = base / "plan.md"
        self.logs = base / "logs"

        header = (
            runner.ROOT / "lab/docs/MVP_TEST_MATRIX.csv"
        ).read_text(encoding="utf-8").splitlines()[0]

        self.matrix.write_text(
            header + "\n",
            encoding="utf-8",
        )

        self.plan.write_text(
            "## S01-F06 — Simulated test\n",
            encoding="utf-8",
        )

        self.argv = [
            "mvp_vlan_runner.py",
            "--run-id", "S01-F06",
            "--port", "sw1p1",
            "--missing-vlan", "10",
            "--execute",
        ]

        self.fault_pings = {
            "vlan10": {"packet_loss_pct": 100.0},
            "vlan20": {"packet_loss_pct": 0.0},
        }

        self.runner_patch = patch.multiple(
            runner,
            MATRIX=self.matrix,
            PLAN=self.plan,
            LOG_DIR=self.logs,
        )

        self.runner_patch.start()
        self.addCleanup(self.runner_patch.stop)

    @staticmethod
    def simulated_diagnosis(target_status):
        # Create a simulated 12-check report
        target = {
            "device": "sw1",
            "component": "sw1p1",
            "status": target_status,
            "evidence": (
                {"missing_vlans": [10]}
                if target_status == "fault_detected"
                else {}
            ),
            "evidence_sources": [
                {"record_id": 999}
            ],
        }

        checks = [target] + [
            {
                "device": f"other{i}",
                "component": "mock",
                "status": "healthy",
            }
            for i in range(11)
        ]

        healthy_count = (
            12 if target_status == "healthy" else 11
        )

        return {
            "summary": {
                "total_checks": 12,
                "healthy": healthy_count,
                "other_findings": 12 - healthy_count,
            },
            "checks": checks,
        }

    # --------------------------------------------------
    # TEST 1: Duplicate Run ID
    # --------------------------------------------------

    def test_duplicate_id_stops_before_network(self):

        self.matrix.write_text(
            "run_id\nS01-F06\n",
            encoding="utf-8",
        )

        with (
            patch.object(sys, "argv", self.argv),
            patch.object(runner, "command") as external,
            patch.object(runner, "verify_healthy") as verify,
            patch.object(runner, "set_trunks") as inject,
        ):
            with self.assertRaises(SystemExit) as error:
                runner.main()

        self.assertIn(
            "Run already recorded",
            str(error.exception),
        )

        external.assert_not_called()
        verify.assert_not_called()
        inject.assert_not_called()

    # --------------------------------------------------
    # TEST 2: Existing JSON Protection
    # --------------------------------------------------

    def test_existing_json_blocks_run(self):

        self.logs.mkdir(parents=True, exist_ok=True)

        log = self.logs / "S01-F06_result.json"
        original = '{"result": "passed"}\n'

        log.write_text(
            original,
            encoding="utf-8",
        )

        with (
            patch.object(sys, "argv", self.argv),
            patch.object(runner, "command") as external,
            patch.object(runner, "verify_healthy") as verify,
            patch.object(runner, "set_trunks") as inject,
        ):
            with self.assertRaises(SystemExit) as error:
                runner.main()

        self.assertIn(
            "Result log already exists",
            str(error.exception),
        )

        external.assert_not_called()
        verify.assert_not_called()
        inject.assert_not_called()

        self.assertEqual(
            log.read_text(encoding="utf-8"),
            original,
        )

    # --------------------------------------------------
    # TEST 3: Preflight Failure Recording
    # --------------------------------------------------

    def test_preflight_failure_is_recorded(self):

        # Use the real CSV schema, but write only to
        # the isolated temporary matrix.
        header = (
            runner.ROOT / "lab/docs/MVP_TEST_MATRIX.csv"
        ).read_text(
            encoding="utf-8"
        ).splitlines()[0]

        self.matrix.write_text(
            header + "\n",
            encoding="utf-8",
        )

        with (
            patch.object(sys, "argv", self.argv),

            patch.object(
                runner,
                "verify_healthy",
                side_effect=RuntimeError(
                    "Simulated preflight failure"
                ),
            ),

            patch.object(
                runner,
                "set_trunks",
            ) as inject,

            patch.object(
                runner,
                "command",
                side_effect=AssertionError(
                    "Unexpected external command"
                ),
            ),
        ):
            try:
                runner.main()
            except (RuntimeError, SystemExit):
                pass

        # No fault injection is allowed.
        inject.assert_not_called()

        # Verify JSON was created.
        log = self.logs / "S01-F06_result.json"

        self.assertTrue(
            log.exists(),
            "Preflight failure must be recorded",
        )

        result = json.loads(
            log.read_text(encoding="utf-8")
        )

        self.assertEqual(
            result["result"],
            "blocked",
        )

        self.assertEqual(
            result["failure_stage"],
            "preflight",
        )

        # Verify CSV was also updated.
        with self.matrix.open(
            newline="",
            encoding="utf-8",
        ) as f:
            rows = list(csv.DictReader(f))

        self.assertEqual(len(rows), 1)

        self.assertEqual(
            rows[0]["run_id"],
            "S01-F06",
        )

        self.assertEqual(
            rows[0]["test_case_id"],
            "S01-F06",
        )

        self.assertEqual(
            rows[0]["run_result"],
            "blocked",
        )

        self.assertEqual(
            rows[0]["failure_stage"],
            "preflight",
        )

    # --------------------------------------------------
    # TEST 4: Diagnosis Failure and Recovery
    # --------------------------------------------------

    def test_diagnosis_failure_still_restores_network(self):

        diagnosis = self.simulated_diagnosis("healthy")

        with (
            patch.object(sys, "argv", self.argv),

            patch.object(
                runner,
                "verify_healthy",
            ) as healthy,

            patch.object(
                runner,
                "set_trunks",
            ) as set_trunks,

            patch.object(
                runner,
                "get_trunks",
                side_effect=lambda port: (
                    "[20]" if port == "sw1p1"
                    else "[10,20]"
                ),
            ),

            patch.object(
                runner,
                "check_connectivity",
                return_value=self.fault_pings,
            ),

            patch.object(
                runner,
                "collect_and_diagnose",
                return_value=(diagnosis, 1.0, 0.01),
            ),

            patch.object(
                runner,
                "command",
                side_effect=AssertionError(
                    "Unexpected external command"
                ),
            ) as external,
        ):
            with self.assertRaises(SystemExit) as error:
                runner.main()

        self.assertEqual(error.exception.code, 1)

        self.assertEqual(set_trunks.call_count, 2)

        set_trunks.assert_any_call(
            "sw1p1",
            [20],
        )

        self.assertEqual(
            set_trunks.call_args.args,
            ("sw1p1", [10, 20]),
        )

        self.assertEqual(healthy.call_count, 2)
        external.assert_not_called()

        log = self.logs / "S01-F06_result.json"
        self.assertTrue(log.exists())

        result = json.loads(
            log.read_text(encoding="utf-8")
        )

        self.assertEqual(
            result["result"],
            "failed",
        )

        self.assertFalse(
            result["diagnosis_correct"],
        )

        self.assertTrue(
            result["recovery_verified"],
        )

        self.assertIn(
            "Diagnosis criteria not met",
            result["error"],
        )

    # --------------------------------------------------
    # TEST 5: Recovery Failure
    # --------------------------------------------------

    def test_recovery_failure_cannot_pass(self):

        diagnosis = self.simulated_diagnosis(
            "fault_detected"
        )

        with (
            patch.object(sys, "argv", self.argv),

            patch.object(
                runner,
                "verify_healthy",
            ) as healthy,

            patch.object(
                runner,
                "set_trunks",
                side_effect=[
                    None,
                    RuntimeError(
                        "Simulated recovery failure"
                    ),
                ],
            ) as set_trunks,

            patch.object(
                runner,
                "get_trunks",
                side_effect=lambda port: (
                    "[20]" if port == "sw1p1"
                    else "[10,20]"
                ),
            ),

            patch.object(
                runner,
                "check_connectivity",
                return_value=self.fault_pings,
            ),

            patch.object(
                runner,
                "collect_and_diagnose",
                return_value=(diagnosis, 1.0, 0.01),
            ),

            patch.object(
                runner,
                "command",
                side_effect=AssertionError(
                    "Unexpected external command"
                ),
            ) as external,
        ):
            with self.assertRaises(SystemExit) as error:
                runner.main()

        self.assertEqual(error.exception.code, 1)

        # Injection succeeded, restoration failed.
        self.assertEqual(set_trunks.call_count, 2)
        self.assertEqual(healthy.call_count, 1)

        external.assert_not_called()

        log = self.logs / "S01-F06_result.json"

        self.assertTrue(log.exists())

        result = json.loads(
            log.read_text(encoding="utf-8")
        )

        self.assertTrue(
            result["diagnosis_correct"],
        )

        self.assertFalse(
            result["recovery_verified"],
        )

        self.assertEqual(
            result["result"],
            "failed",
        )

        self.assertIn(
            "Simulated recovery failure",
            result["recovery_error"],
        )

    # --------------------------------------------------
    # TEST 6: Collection Failure and Recovery
    # --------------------------------------------------

    def test_collection_failure_triggers_recovery(self):

        with (
            patch.object(sys, "argv", self.argv),

            patch.object(
                runner,
                "verify_healthy",
            ) as healthy,

            patch.object(
                runner,
                "set_trunks",
            ) as set_trunks,

            patch.object(
                runner,
                "get_trunks",
                side_effect=lambda port: (
                    "[20]" if port == "sw1p1"
                    else "[10,20]"
                ),
            ),

            patch.object(
                runner,
                "check_connectivity",
                return_value=self.fault_pings,
            ),

            patch.object(
                runner,
                "collect_and_diagnose",
                side_effect=RuntimeError(
                    "Simulated collection failure"
                ),
            ),

            patch.object(
                runner,
                "command",
                side_effect=AssertionError(
                    "Unexpected external command"
                ),
            ) as external,
        ):
            with self.assertRaises(SystemExit) as error:
                runner.main()

        self.assertEqual(error.exception.code, 1)

        # Recovery must still be attempted.
        self.assertEqual(set_trunks.call_count, 2)

        self.assertEqual(
            set_trunks.call_args.args,
            ("sw1p1", [10, 20]),
        )

        self.assertEqual(healthy.call_count, 2)
        external.assert_not_called()

        log = self.logs / "S01-F06_result.json"

        self.assertTrue(log.exists())

        result = json.loads(
            log.read_text(encoding="utf-8")
        )

        self.assertEqual(
            result["result"],
            "failed",
        )

        self.assertTrue(
            result["recovery_verified"],
        )

        self.assertIn(
            "Simulated collection failure",
            result["error"],
        )
            # --------------------------------------------------
    # TEST 7: Successful Run and Safe Reconciliation
    # --------------------------------------------------

    def test_success_then_reconcile_without_reinjection(self):

        diagnosis = self.simulated_diagnosis("fault_detected")

        # Phase 1: A completely successful simulated run.
        with (
            patch.object(sys, "argv", self.argv),

            patch.object(
                runner, "verify_healthy"
            ) as healthy,

            patch.object(
                runner, "set_trunks"
            ) as set_trunks,

            patch.object(
                runner,
                "get_trunks",
                side_effect=lambda port: (
                    "[20]" if port == "sw1p1"
                    else "[10,20]"
                ),
            ),

            patch.object(
                runner,
                "check_connectivity",
                return_value=self.fault_pings,
            ),

            patch.object(
                runner,
                "collect_and_diagnose",
                return_value=(diagnosis, 1.0, 0.01),
            ),

            patch.object(
                runner,
                "command",
                side_effect=AssertionError(
                    "Unexpected external command"
                ),
            ) as external,
        ):
            runner.main()

        self.assertEqual(set_trunks.call_count, 2)
        self.assertEqual(healthy.call_count, 2)
        external.assert_not_called()

        log = self.logs / "S01-F06_result.json"

        original_json = log.read_text(encoding="utf-8")
        result = json.loads(original_json)

        self.assertEqual(result["result"], "passed")
        self.assertTrue(result["diagnosis_correct"])
        self.assertTrue(result["recovery_verified"])

        with self.matrix.open(
            newline="",
            encoding="utf-8",
        ) as f:
            rows = list(csv.DictReader(f))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["run_result"], "passed")
        self.assertEqual(rows[0]["run_id"], "S01-F06")
        self.assertEqual(rows[0]["failure_stage"], "")

        # Test variation: Simulate a missing CSV entry.
        # Only the temporary test matrix is modified.
        header = self.matrix.read_text(
            encoding="utf-8"
        ).splitlines()[0]

        self.matrix.write_text(
            header + "\n",
            encoding="utf-8",
        )

        # Recover the CSV entry from JSON without
        # any network commands or fault injection.
        with (
            patch.object(
                sys,
                "argv",
                [
                    "mvp_vlan_runner.py",
                    "--run-id", "S01-F06",
                    "--reconcile",
                ],
            ),

            patch.object(runner, "command") as external,
            patch.object(runner, "verify_healthy") as verify,
            patch.object(runner, "set_trunks") as inject,
            patch.object(runner, "check_connectivity") as ping,
            patch.object(runner, "collect_and_diagnose") as collect,
        ):
            runner.main()

        external.assert_not_called()
        verify.assert_not_called()
        inject.assert_not_called()
        ping.assert_not_called()
        collect.assert_not_called()

        # Original JSON must remain unchanged.
        self.assertEqual(
            log.read_text(encoding="utf-8"),
            original_json,
        )

        with self.matrix.open(
            newline="",
            encoding="utf-8",
        ) as f:
            recovered_rows = list(csv.DictReader(f))

        self.assertEqual(len(recovered_rows), 1)
        self.assertEqual(
            recovered_rows[0]["run_result"],
            "passed",
        )
        self.assertEqual(
            recovered_rows[0]["run_id"],
            "S01-F06",
        )


if __name__ == "__main__":
    unittest.main()