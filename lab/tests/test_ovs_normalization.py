import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ovs_normalization import normalize_ovs_value
from evidence_parser import parse_switch_port


class TestOVSNormalization(unittest.TestCase):

    def test_single_vlan(self):
        vlans = normalize_ovs_value(20, "trunks")
        self.assertEqual(vlans, [20])

        output = json.dumps({
            "name": "sw1p1",
            "vlan_mode": "trunk",
            "tag": [],
            "trunks": vlans,
        })
        parsed = parse_switch_port(output)
        self.assertEqual(parsed["vlans"], [20])

    def test_multiple_vlans(self):
        value = ["set", [10, 20]]
        self.assertEqual(
            normalize_ovs_value(value, "trunks"),
            [10, 20],
        )

    def test_access_port(self):
        self.assertEqual(
            normalize_ovs_value(10, "tag"),
            10,
        )

    def test_empty_vlan_set(self):
        value = ["set", []]
        self.assertEqual(
            normalize_ovs_value(value, "trunks"),
            [],
        )


if __name__ == "__main__":
    unittest.main()
