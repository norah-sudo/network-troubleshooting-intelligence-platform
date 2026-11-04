import sys
import unittest
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "scripts")
)

from evidence_parser import parse_interface
from interface_diagnosis import diagnose_interface


EXPECTED = {
    "interface": "eth1",
    "interface_status": "up",
    "line_protocol": "up",
}


class TestInterfaceParser(unittest.TestCase):

    def test_healthy_interface(self):
        output = "Interface eth1 is up, line protocol is up"
        observed = parse_interface(output)
        result = diagnose_interface("r1", EXPECTED, observed)
        self.assertEqual(result["status"], "healthy")

    def test_down_without_line_protocol(self):
        output = (
            "Interface eth1 is down\n"
            "  Link downs: 3\n"
            "  flags: <BROADCAST,MULTICAST>"
        )
        observed = parse_interface(output)
        self.assertEqual(observed["interface_status"], "down")
        self.assertIsNone(observed["line_protocol"])

        result = diagnose_interface("r1", EXPECTED, observed)
        self.assertEqual(result["status"], "fault_detected")
        self.assertEqual(result["issue"], "Interface down")

    def test_administratively_down(self):
        observed = parse_interface(
            "Interface eth1 is administratively down"
        )
        result = diagnose_interface("r1", EXPECTED, observed)
        self.assertEqual(result["status"], "fault_detected")
        self.assertEqual(
            result["issue"], "Interface administratively down"
        )

    def test_line_protocol_down(self):
        observed = parse_interface(
            "Interface eth1 is up, line protocol is down"
        )
        result = diagnose_interface("r1", EXPECTED, observed)
        self.assertEqual(result["status"], "fault_detected")
        self.assertEqual(result["issue"], "Line protocol down")

    def test_invalid_output_rejected(self):
        with self.assertRaises(ValueError):
            parse_interface("Unexpected device output")

    def test_up_without_protocol_rejected(self):
        with self.assertRaises(ValueError):
            parse_interface("Interface eth1 is up")


if __name__ == "__main__":
    unittest.main()
