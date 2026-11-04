
def compare_port_snapshots(before, after):
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise ValueError("Invalid configuration snapshots")

    port = before.get("name")

    if not isinstance(port, str) or not port or after.get("name") != port:
        raise ValueError("Snapshots belong to different ports")

    changes = []

    for field in ("mode", "vlans", "vlan"):
        old_value = before.get(field)
        new_value = after.get(field)

        if (
            field == "vlans"
            and isinstance(old_value, list)
            and isinstance(new_value, list)
        ):
            # VLAN membership matters, not list order.
            changed = set(old_value) != set(new_value)
        else:
            changed = old_value != new_value

        if changed:
            changes.append({
                "field": field,
                "before": old_value,
                "after": new_value,
            })

    return {
        "port": port,
        "changed": bool(changes),
        "changes": changes,
    }
