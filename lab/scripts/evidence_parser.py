
import re


def parse_interface(output):
    pattern = (
        r"^Interface\s+(\S+)\s+is\s+"
        r"(administratively down|up|down)"
        r"(?:,\s+line protocol is\s+(up|down))?\s*$"
    )

    match = re.search(
        pattern, output, re.IGNORECASE | re.MULTILINE
    )

    if not match:
        raise ValueError("Unable to parse interface status")

    interface, status, protocol = match.groups()
    status = status.lower()

    if protocol is None and status == "up":
        raise ValueError("Line protocol not reported for UP interface")

    return {
        "interface": interface,
        "interface_status": status,
        "line_protocol": protocol.lower() if protocol else None,
    }


def parse_ospf_neighbors(output):
    lines = output.strip().splitlines()

    # Confirm this is an OSPF neighbor table
    header_index = next(
        (
            i for i, line in enumerate(lines)
            if "Neighbor ID" in line and "State" in line
        ),
        None
    )

    if header_index is None:
        raise ValueError("Invalid OSPF neighbor output")

    neighbors = []

    for line in lines[header_index + 1:]:
        if not line.strip():
            continue

        columns = line.split()

        if len(columns) < 7:
            raise ValueError("Invalid OSPF neighbor row")

        neighbor_id = columns[0]
        state_parts = columns[2].split("/", 1)

        neighbors.append({
            "neighbor_id": neighbor_id,
            "state": state_parts[0].capitalize(),
            "role": state_parts[1] if len(state_parts) > 1 else None,
        })

    return neighbors

def parse_switch_port(output):
    import json

    data = json.loads(output)

    required = ("name", "vlan_mode", "tag", "trunks")

    if not isinstance(data, dict):
        raise ValueError("Invalid switch port data")

    if any(key not in data for key in required):
        raise ValueError("Missing switch port information")

    mode = data["vlan_mode"]

    if mode == "trunk":
        vlans = data["trunks"]

        if not isinstance(vlans, list) or any(
            type(vlan) is not int for vlan in vlans
        ):
            raise ValueError("Invalid trunk VLANs")

        return {
            "name": data["name"],
            "mode": "trunk",
            "vlans": sorted(vlans),
        }

    elif mode == "access":
        vlan = data["tag"]

        if type(vlan) is not int:
            raise ValueError("Invalid access VLAN")

        return {
            "name": data["name"],
            "mode": "access",
            "vlan": vlan,
        }

    else:
        raise ValueError("Unsupported VLAN mode")
