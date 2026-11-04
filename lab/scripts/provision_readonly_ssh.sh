#!/bin/sh
set -eu

# Work from the lab directory.
cd "$(dirname "$0")/.."

# Locate the project owner's SSH public key.
PROJECT_OWNER="${SUDO_USER:-$(id -un)}"
PROJECT_HOME=$(getent passwd "$PROJECT_OWNER" | cut -d: -f6)

if [ -z "$PROJECT_HOME" ]; then
    echo "ERROR: Cannot determine project owner's home directory." >&2
    exit 1
fi

PUBLIC_KEY="$PROJECT_HOME/.local/share/network-troubleshooting-platform/collector_ed25519.pub"

if [ ! -r "$PUBLIC_KEY" ]; then
    echo "ERROR: Collector public key not found." >&2
    exit 1
fi

if ! ssh-keygen -l -f "$PUBLIC_KEY" >/dev/null 2>&1; then
    echo "ERROR: Invalid collector public key." >&2
    exit 1
fi

if [ "$(wc -l < "$PUBLIC_KEY")" -ne 1 ]; then
    echo "ERROR: Expected exactly one public key." >&2
    exit 1
fi

# Configure both FRRouting containers.
for ROUTER in r1 r2; do

    CONTAINER="clab-ospftest-$ROUTER"

    echo "Provisioning read-only SSH on $ROUTER..."

    # Create a dedicated account if it does not exist.
    docker exec -u root "$CONTAINER" sh -c '
        if ! id collector >/dev/null 2>&1; then
            adduser -D -s /bin/sh -G frrvty collector
        fi

        # Permit key authentication without a usable password.
        sed -i "s/^collector:[^:]*:/collector:*NP*:/" /etc/shadow

        mkdir -p /home/collector/.ssh
        chown collector:frrvty /home/collector/.ssh
        chmod 700 /home/collector/.ssh
    '

    # Install the command-restriction script.
    docker cp \
        scripts/readonly_ssh_command.sh \
        "${CONTAINER}:/usr/local/bin/readonly_ssh_command.sh"

    docker exec -u root "$CONTAINER" sh -c '
        chown root:root /usr/local/bin/readonly_ssh_command.sh
        chmod 755 /usr/local/bin/readonly_ssh_command.sh
    '

    # Install the public key with SSH restrictions.
    docker exec -u root -i "$CONTAINER" sh -c '
        IFS= read -r key
        umask 077

        printf "restrict,command=\"/usr/local/bin/readonly_ssh_command.sh\" %s\n" "$key" > /home/collector/.ssh/authorized_keys

        chown collector:frrvty /home/collector/.ssh/authorized_keys
        chmod 600 /home/collector/.ssh/authorized_keys
    ' < "$PUBLIC_KEY"

    echo "PASS: Read-only SSH provisioned on $ROUTER"

done