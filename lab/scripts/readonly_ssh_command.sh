#!/bin/sh
set -eu

# Only these two diagnostic commands are permitted.
# SSH_ORIGINAL_COMMAND contains the command requested by the SSH client.

case "${SSH_ORIGINAL_COMMAND:-}" in

    "show ip ospf neighbor")
        exec /usr/bin/vtysh -c "show ip ospf neighbor"
        ;;

    "show interface eth1")
        exec /usr/bin/vtysh -c "show interface eth1"
        ;;

    *)
        printf '%s\n' "ERROR: SSH command not permitted for collector." >&2
        exit 126
        ;;

esac