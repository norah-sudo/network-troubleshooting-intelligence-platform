"""Normalize OVSDB JSON values for switch evidence collection."""


def normalize_ovs_value(value, field):
    if isinstance(value, list) and len(value) == 2 and value[0] == "set":
        value = value[1]

    if field == "trunks" and type(value) is int:
        return [value]

    return value
