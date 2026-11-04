import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import mvp_change_runner as runner


# --------------------------------------------------
# PROTECTED NETWORK CHANGES
# --------------------------------------------------

class TestMVPChangeRunner(unittest.TestCase):

    def test_restores_both_ports_after_failure(self):
        state = {
            "sw1p1": [10, 20],
            "sw2p1": [10, 20],
        }

        def fake_snapshot(port):
            return {
                "name": port,
                "mode": "trunk",
                "vlans": state[port].copy(),
            }, "simulated-time"

        def fake_set_trunks(port, vlans):
            state[port] = vlans.copy()

        with (
            patch.object(runner, "verify_healthy") as health,
            patch.object(
                runner,
                "capture_port_snapshot",
                side_effect=fake_snapshot,
            ),
            patch.object(
                runner,
                "set_trunks",
                side_effect=fake_set_trunks,
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "Simulated failure",
            ):
                with runner.protected_trunk_changes() as change:
                    change("sw1p1", [20])
                    change("sw2p1", [20])
                    raise RuntimeError("Simulated failure")

        self.assertEqual(
            state,
            {
                "sw1p1": [10, 20],
                "sw2p1": [10, 20],
            },
        )

        self.assertEqual(health.call_count, 2)

    def test_recovery_failure_is_reported(self):
        current_vlans = [10, 20]

        def fake_snapshot(port):
            return {
                "name": port,
                "mode": "trunk",
                "vlans": current_vlans.copy(),
            }, "simulated-time"

        def fake_set_trunks(port, vlans):
            if vlans == [10, 20]:
                raise RuntimeError("Simulated restore failure")

            current_vlans[:] = vlans

        with (
            patch.object(runner, "verify_healthy"),
            patch.object(
                runner,
                "capture_port_snapshot",
                side_effect=fake_snapshot,
            ),
            patch.object(
                runner,
                "set_trunks",
                side_effect=fake_set_trunks,
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "Recovery failed",
            ):
                with runner.protected_trunk_changes() as change:
                    change("sw1p1", [20])


# --------------------------------------------------
# S04-F01: RELEVANT CHANGE CORRELATION
# --------------------------------------------------

class TestS04CorrelationIntegration(unittest.TestCase):

    def test_relevant_change_before_incident(self):
        report = {
            "checks": [{
                "device": "sw1",
                "component": "sw1p1",
                "status": "fault_detected",
                "evidence": {"missing_vlans": [10]},
            }]
        }

        before = {
            "name": "sw1p1",
            "mode": "trunk",
            "vlans": [10, 20],
        }

        after = {
            "name": "sw1p1",
            "mode": "trunk",
            "vlans": [20],
        }

        failed_ping = {
            "source": "hr1",
            "destination": "192.168.10.12",
            "packet_loss_pct": 100.0,
        }

        with patch.object(runner, "print_report"):
            correlation = runner.attach_s04_correlation(
                report,
                "S04-F01-UNIT",
                before,
                after,
                "2026-11-01T17:00:00+00:00",
                "2026-11-01T17:01:00+00:00",
                "2026-11-01T17:02:00+00:00",
                failed_ping,
            )

        self.assertEqual(
            correlation["assessment"],
            "candidate_for_investigation",
        )

        self.assertEqual(
            correlation["network_impact"]["status"],
            "potential_impact",
        )

        self.assertEqual(
            correlation["timing"]["status"],
            "before_first_observation",
        )

        self.assertIn(
            "Causation is not established",
            correlation["conclusion"],
        )


# --------------------------------------------------
# S04-F02: UNRELATED CHANGE AND RECOVERY
# --------------------------------------------------

class TestS04F02Runner(unittest.TestCase):

    def test_unrelated_change_and_recovery(self):
        from datetime import datetime, timedelta, timezone
        from itertools import count

        # Simulated trunk configurations.
        state = {
            "sw1p4": [10, 20],
            "sw2p1": [10, 20],
        }

        # Simulated UTC timestamps.
        base = datetime(
            2026, 11, 3,
            tzinfo=timezone.utc,
        )

        ticks = count()

        def fake_snapshot(port):
            timestamp = (
                base + timedelta(seconds=next(ticks))
            ).isoformat()

            return {
                "name": port,
                "mode": "trunk",
                "vlans": state[port].copy(),
            }, timestamp

        def fake_set_trunks(port, vlans):
            state[port] = vlans.copy()

        def fake_ping(source, destination):
            # HR connectivity fails only when VLAN 10
            # is removed from the actual service path.
            if source == "hr1":
                loss = (
                    100.0
                    if 10 not in state["sw2p1"]
                    else 0.0
                )
            else:
                loss = 0.0

            return {
                "source": source,
                "destination": destination,
                "packet_loss_pct": loss,
            }

        # Simulated evidence of the real fault location.
        fault_check = {
            "device": "sw2",
            "component": "sw2p1",
            "status": "fault_detected",
            "evidence": {
                "missing_vlans": [10],
            },
            "evidence_sources": [
                {"record_id": 999},
            ],
        }

        healthy_checks = [
            {
                "device": f"mock{i}",
                "component": "mock",
                "status": "healthy",
            }
            for i in range(11)
        ]

        report = {
            "generated_at": "2026-11-03T00:01:01+00:00",
            "summary": {
                "total_checks": 12,
                "healthy": 11,
                "other_findings": 1,
            },
            "checks": [fault_check] + healthy_checks,
        }

        # Replace all network operations with mocks.
        with (
            patch.object(runner, "verify_healthy") as health,
            patch.object(
                runner,
                "capture_port_snapshot",
                side_effect=fake_snapshot,
            ),
            patch.object(
                runner,
                "set_trunks",
                side_effect=fake_set_trunks,
            ),
            patch.object(
                runner,
                "ping",
                side_effect=fake_ping,
            ),
            patch.object(
                runner,
                "collect_and_diagnose",
                return_value=(report, 1.0, 0.001),
            ),
            patch.object(
                runner,
                "utc_now",
                return_value="2026-11-03T00:01:00+00:00",
            ),
            patch.object(runner, "print_report"),
        ):
            result = runner.run_s04_f02()

        # The unrelated change must be excluded.
        self.assertEqual(
            result["correlation"]["assessment"],
            "no_direct_link_found",
        )

        self.assertEqual(
            result["correlation"]["network_impact"]["status"],
            "not_on_path",
        )

        # HR connectivity must survive the unrelated change.
        self.assertEqual(
            result["unaffected_ping"]["packet_loss_pct"],
            0.0,
        )

        # The actual sw2p1 fault must interrupt VLAN 10.
        self.assertEqual(
            result["failed_ping"]["packet_loss_pct"],
            100.0,
        )

        # VLAN 20 must remain operational.
        self.assertEqual(
            result["control_ping"]["packet_loss_pct"],
            0.0,
        )

        # Both ports must return to their original configuration.
        self.assertEqual(
            state,
            {
                "sw1p4": [10, 20],
                "sw2p1": [10, 20],
            },
        )

        self.assertTrue(
            result["recovery_verified"]
        )

        # Verify baseline before and after the simulated run.
        self.assertEqual(
            health.call_count,
            2,
        )
class TestS04DefaultPermissions(unittest.TestCase):

    def test_sw1p4_rejected_by_default_guard(self):
        with (
            patch.object(runner, "verify_healthy"),
            patch.object(runner, "set_trunks") as set_trunks,
        ):
            with self.assertRaisesRegex(
                ValueError,
                "Unapproved port: sw1p4",
            ):
                with runner.protected_trunk_changes() as change:
                    change("sw1p4", [10, 20, 30])

            set_trunks.assert_not_called()



      # --------------------------------------------------
# S04-F03: CHANGE AFTER INCIDENT TESTS
# --------------------------------------------------

class TestS04F03Runner(unittest.TestCase):

    def setUp(self):
        from datetime import datetime, timezone
        from itertools import count

        self.base = datetime(
            2026, 11, 3, 10, 0, 0,
            tzinfo=timezone.utc,
        )
        self.ticks = count()

        self.state = {
            "sw1p1": [10, 20],
            "sw2p1": [10, 20],
        }

        self.force_no_outage = False
        self.collection_failure = False
        self.health_calls = 0

        def fault_check(device, port, record_id):
            return {
                "device": device,
                "component": port,
                "status": "fault_detected",
                "evidence": {
                    "missing_vlans": [10],
                },
                "evidence_sources": [
                    {"record_id": record_id},
                ],
            }

        self.report = {
            "generated_at": "2026-11-03T10:00:30+00:00",
            "summary": {
                "total_checks": 12,
                "healthy": 10,
                "other_findings": 2,
            },
            "checks": [
                fault_check("sw1", "sw1p1", 1001),
                fault_check("sw2", "sw2p1", 1002),
            ] + [
                {
                    "device": f"mock{i}",
                    "component": "mock",
                    "status": "healthy",
                }
                for i in range(10)
            ],
        }

    def fake_time(self):
        from datetime import timedelta

        return (
            self.base
            + timedelta(seconds=next(self.ticks))
        ).isoformat()

    def fake_snapshot(self, port):
        return {
            "name": port,
            "mode": "trunk",
            "vlans": self.state[port].copy(),
        }, self.fake_time()

    def fake_set_trunks(self, port, vlans):
        self.state[port] = vlans.copy()

    def fake_ping(self, source, destination):
        if source == "hr1":
            if self.force_no_outage:
                loss = 0.0
            else:
                loss = (
                    100.0
                    if (
                        10 not in self.state["sw1p1"]
                        or 10 not in self.state["sw2p1"]
                    )
                    else 0.0
                )
        else:
            loss = 0.0

        return {
            "source": source,
            "destination": destination,
            "packet_loss_pct": loss,
        }

    def fake_collect(self):
        if self.collection_failure:
            raise RuntimeError(
                "Simulated collection failure"
            )

        return self.report, 1.0, 0.001

    def execute_mocked_run(self):
        with (
            patch.object(
                runner,
                "verify_healthy",
            ) as health,
            patch.object(
                runner,
                "capture_port_snapshot",
                side_effect=self.fake_snapshot,
            ),
            patch.object(
                runner,
                "set_trunks",
                side_effect=self.fake_set_trunks,
            ),
            patch.object(
                runner,
                "ping",
                side_effect=self.fake_ping,
            ),
            patch.object(
                runner,
                "collect_and_diagnose",
                side_effect=self.fake_collect,
            ),
            patch.object(
                runner,
                "utc_now",
                side_effect=self.fake_time,
            ),
            patch.object(
                runner,
                "print_report",
            ),
        ):
            try:
                return runner.run_s04_f03()
            finally:
                self.health_calls = health.call_count

    def test_change_after_incident_and_recovery(self):
        from datetime import datetime

        result = self.execute_mocked_run()

        correlation = result["correlation"]

        self.assertEqual(
            correlation["assessment"],
            "not_initial_trigger",
        )

        self.assertEqual(
            correlation["network_impact"]["status"],
            "potential_impact",
        )

        self.assertEqual(
            correlation["timing"]["status"],
            "after_first_observation",
        )

        # The incident must be observed before
        # the sw1p1 snapshot/change window.
        observed = datetime.fromisoformat(
            result["first_observed_at"]
        )
        before = datetime.fromisoformat(
            result["before_time"]
        )
        after = datetime.fromisoformat(
            result["after_time"]
        )

        self.assertLess(observed, before)
        self.assertLess(before, after)

        self.assertEqual(
            result["failed_ping"]["packet_loss_pct"],
            100.0,
        )

        self.assertEqual(
            result["control_ping"]["packet_loss_pct"],
            0.0,
        )

        # Both ports must be restored.
        self.assertEqual(
            self.state,
            {
                "sw1p1": [10, 20],
                "sw2p1": [10, 20],
            },
        )

        self.assertTrue(result["recovery_verified"])
        self.assertEqual(self.health_calls, 2)

        # Verify the Test Matrix row without saving it.
        row = runner.build_s04_f03_matrix_row(result)

        self.assertEqual(
            row["test_case_id"],
            "S04-F03",
        )

        self.assertEqual(
            row["run_result"],
            "passed",
        )

        self.assertEqual(
            row["recovery_verified"],
            "true",
        )

        self.assertEqual(
            row["evidence_record_ids"],
            "1001;1002",
        )

        # An unverified recovery must never pass.
        invalid_result = {
            **result,
            "recovery_verified": False,
        }

        with self.assertRaisesRegex(
            RuntimeError,
            "Recovery was not verified",
        ):
            runner.build_s04_f03_matrix_row(
                invalid_result
            )

    def test_missing_incident_restores_network(self):
        self.force_no_outage = True

        with self.assertRaisesRegex(
            RuntimeError,
            "Expected VLAN 10 outage not observed",
        ):
            self.execute_mocked_run()

        self.assertEqual(
            self.state,
            {
                "sw1p1": [10, 20],
                "sw2p1": [10, 20],
            },
        )

        self.assertEqual(self.health_calls, 2)

    def test_collection_failure_restores_both_ports(self):
        self.collection_failure = True

        with self.assertRaisesRegex(
            RuntimeError,
            "Simulated collection failure",
        ):
            self.execute_mocked_run()

        self.assertEqual(
            self.state,
            {
                "sw1p1": [10, 20],
                "sw2p1": [10, 20],
            },
        )

        self.assertEqual(self.health_calls, 2)
# --------------------------------------------------
# S04-F04: NO-CHANGE CONTROL TESTS
# --------------------------------------------------

class TestS04F04Runner(unittest.TestCase):

    def setUp(self):
        from datetime import datetime, timezone
        from itertools import count

        self.base = datetime(
            2026, 11, 3, 11, 0, 0,
            tzinfo=timezone.utc,
        )
        self.ticks = count()

        self.state = {
            "sw1p1": [10, 20],
            "sw2p1": [10, 20],
        }

        self.force_no_outage = False
        self.collection_failure = False
        self.health_calls = 0

        self.report = {
            "generated_at": "2026-11-03T11:00:30+00:00",
            "summary": {
                "total_checks": 12,
                "healthy": 11,
                "other_findings": 1,
            },
            "checks": [
                {
                    "device": "sw1",
                    "component": "sw1p1",
                    "status": "healthy",
                    "evidence_sources": [
                        {"record_id": 1201},
                    ],
                },
                {
                    "device": "sw2",
                    "component": "sw2p1",
                    "status": "fault_detected",
                    "evidence": {
                        "missing_vlans": [10],
                    },
                    "evidence_sources": [
                        {"record_id": 1202},
                    ],
                },
            ] + [
                {
                    "device": f"mock{i}",
                    "component": "mock",
                    "status": "healthy",
                }
                for i in range(10)
            ],
        }

    def fake_time(self):
        from datetime import timedelta

        return (
            self.base
            + timedelta(seconds=next(self.ticks))
        ).isoformat()

    def fake_snapshot(self, port):
        return {
            "name": port,
            "mode": "trunk",
            "vlans": self.state[port].copy(),
        }, self.fake_time()

    def fake_set_trunks(self, port, vlans):
        self.state[port] = vlans.copy()

    def fake_ping(self, source, destination):
        if source == "hr1":
            if self.force_no_outage:
                loss = 0.0
            else:
                loss = (
                    100.0
                    if 10 not in self.state["sw2p1"]
                    else 0.0
                )
        else:
            loss = 0.0

        return {
            "source": source,
            "destination": destination,
            "packet_loss_pct": loss,
        }

    def fake_collect(self):
        if self.collection_failure:
            raise RuntimeError(
                "Simulated collection failure"
            )

        return self.report, 1.0, 0.001

    def execute_mocked_run(self):
        with (
            patch.object(
                runner,
                "verify_healthy",
            ) as health,
            patch.object(
                runner,
                "capture_port_snapshot",
                side_effect=self.fake_snapshot,
            ),
            patch.object(
                runner,
                "set_trunks",
                side_effect=self.fake_set_trunks,
            ),
            patch.object(
                runner,
                "ping",
                side_effect=self.fake_ping,
            ),
            patch.object(
                runner,
                "collect_and_diagnose",
                side_effect=self.fake_collect,
            ),
            patch.object(
                runner,
                "utc_now",
                side_effect=self.fake_time,
            ),
            patch.object(
                runner,
                "print_report",
            ),
        ):
            try:
                return runner.run_s04_f04()
            finally:
                self.health_calls = health.call_count

    def test_no_change_detected_and_recovery(self):
        from datetime import datetime

        result = self.execute_mocked_run()

        correlation = result["correlation"]

        self.assertEqual(
            correlation["assessment"],
            "no_change_detected",
        )

        self.assertEqual(
            correlation["network_impact"]["status"],
            "no_change",
        )

        self.assertFalse(
            correlation["configuration_change"]["changed"]
        )

        # The control port must remain identical.
        self.assertEqual(
            result["before_snapshot"],
            result["after_snapshot"],
        )

        # The first snapshot must precede the incident;
        # the second must follow its observation.
        before = datetime.fromisoformat(
            result["before_time"]
        )
        observed = datetime.fromisoformat(
            result["first_observed_at"]
        )
        after = datetime.fromisoformat(
            result["after_time"]
        )

        self.assertLess(before, observed)
        self.assertLess(observed, after)

        self.assertEqual(
            result["failed_ping"]["packet_loss_pct"],
            100.0,
        )

        self.assertEqual(
            result["control_ping"]["packet_loss_pct"],
            0.0,
        )

        # The real fault port must be restored.
        self.assertEqual(
            self.state,
            {
                "sw1p1": [10, 20],
                "sw2p1": [10, 20],
            },
        )

        self.assertTrue(result["recovery_verified"])
        self.assertEqual(self.health_calls, 2)

        # Validate the matrix row without saving it.
        row = runner.build_s04_f04_matrix_row(result)

        self.assertEqual(
            row["test_case_id"],
            "S04-F04",
        )

        self.assertEqual(
            row["run_result"],
            "passed",
        )

        self.assertEqual(
            row["evidence_record_ids"],
            "1201;1202",
        )

        # Unverified recovery must be rejected.
        invalid_result = {
            **result,
            "recovery_verified": False,
        }

        with self.assertRaisesRegex(
            RuntimeError,
            "Recovery was not verified",
        ):
            runner.build_s04_f04_matrix_row(
                invalid_result
            )

    def test_missing_incident_restores_network(self):
        self.force_no_outage = True

        with self.assertRaisesRegex(
            RuntimeError,
            "Expected VLAN 10 outage not observed",
        ):
            self.execute_mocked_run()

        self.assertEqual(
            self.state,
            {
                "sw1p1": [10, 20],
                "sw2p1": [10, 20],
            },
        )

        self.assertEqual(self.health_calls, 2)

    def test_collection_failure_restores_network(self):
        self.collection_failure = True

        with self.assertRaisesRegex(
            RuntimeError,
            "Simulated collection failure",
        ):
            self.execute_mocked_run()

        self.assertEqual(
            self.state,
            {
                "sw1p1": [10, 20],
                "sw2p1": [10, 20],
            },
        )

        self.assertEqual(self.health_calls, 2)
if __name__ == "__main__":
    unittest.main()