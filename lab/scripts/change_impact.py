
def analyze_change_impact(change_report, incident):
    port = change_report["port"]
    vlan = incident["vlan"]
    path_ports = incident["path_ports"]

    if not change_report["changed"]:
        return {
            "status": "no_change",
            "reason": "No configuration change detected.",
        }

    if port not in path_ports:
        return {
            "status": "not_on_path",
            "reason": "Changed port is outside the expected service path.",
        }

    for change in change_report["changes"]:
        field = change["field"]
        before = change["before"]
        after = change["after"]

        if field == "vlans":
            if (
                not isinstance(before, list)
                or not isinstance(after, list)
                or not before
                or not after
            ):
                return {
                    "status": "needs_review",
                    "reason": "Trunk VLAN change requires further review.",
                }

            removed = set(before) - set(after)

            if vlan in removed:
                return {
                    "status": "potential_impact",
                    "reason": f"VLAN {vlan} removed from a port on the service path.",
                }

        elif field == "vlan":
            if vlan in (before, after):
                return {
                    "status": "potential_impact",
                    "reason": "Access VLAN assignment changed on the service path.",
                }

        elif field == "mode":
            return {
                "status": "potential_impact",
                "reason": "Port mode changed on the service path.",
            }

    return {
        "status": "no_direct_impact_found",
        "reason": "No direct impact on the investigated VLAN identified.",
    }
