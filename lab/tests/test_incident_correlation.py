import sys
import unittest
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "scripts")
)

from incident_correlation import correlate_incident


INCIDENT = {
    "vlan": 10,
    "path_ports": ["sw1p2", "sw1p1", "sw2p1", "sw2p2"],
}

BEFORE = {
    "name": "sw1p1",
    "mode": "trunk",
    "vlans": [10, 20],
}


class TestIncidentCorrelation(unittest.TestCase):

    def test_relevant_vlan_removal(self):
        after = {
            "name": "sw1p1",
            "mode": "trunk",
            "vlans": [20],
        }

        result = correlate_incident(
            BEFORE,
            after,
            INCIDENT,
            "2026-10-28T17:01:12+00:00",
            "2026-10-28T17:03:12+00:00",
            "2026-10-28T17:10:34+00:00",
        )

        self.assertEqual(
            result["assessment"],
            "candidate_for_investigation",
        )
        self.assertEqual(
            result["network_impact"]["status"],
            "potential_impact",
        )
        self.assertEqual(
            result["timing"]["status"],
            "before_first_observation",
        )

    def test_unrelated_vlan_addition(self):
        after = {
            "name": "sw1p1",
            "mode": "trunk",
            "vlans": [10, 20, 30],
        }

        result = correlate_incident(
            BEFORE,
            after,
            INCIDENT,
            "2026-10-28T17:19:05+00:00",
            "2026-10-28T17:20:49+00:00",
            "2026-10-28T17:10:34+00:00",
        )

        self.assertEqual(
            result["assessment"],
            "no_direct_link_found",
        )
        self.assertEqual(
            result["network_impact"]["status"],
            "no_direct_impact_found",
        )
        self.assertEqual(
            result["timing"]["status"],
            "after_first_observation",
        )


if __name__ == "__main__":
    unittest.main()
