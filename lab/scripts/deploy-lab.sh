
#!/bin/sh
set -eu

cd "$(dirname "$0")/.."

# Start Open vSwitch and create bridges if missing
service openvswitch-switch start
ovs-vsctl --may-exist add-br sw1
ovs-vsctl --may-exist add-br sw2

# Deploy Containerlab topology
containerlab deploy -t ospf-test.clab.yml

# Restore host IP addresses and VLAN configurations
sh scripts/restore-network.sh

# Wait for FRRouting and restore OSPF if needed
for router in r1 r2; do
  attempt=0

  until docker exec "clab-ospftest-$router" vtysh -c "show version" >/dev/null 2>&1; do
    attempt=$((attempt + 1))

    if [ "$attempt" -ge 15 ]; then
      echo "ERROR: FRRouting not ready on $router" >&2
      exit 1
    fi

    sleep 2
  done

  if ! docker exec "clab-ospftest-$router" vtysh -c "show running-config" | grep -q '^router ospf$'; then
    echo "Restoring OSPF configuration on $router..."
    docker exec "clab-ospftest-$router" vtysh -b
  fi
done

# Verify OSPF configuration on both routers
for router in r1 r2; do
  if ! docker exec "clab-ospftest-$router" vtysh -c "show running-config" | grep -q '^router ospf$'; then
    echo "ERROR: OSPF configuration missing on $router" >&2
    exit 1
  fi
done

echo "OSPF configuration verified on R1 and R2."


# Verify OSPF neighbor adjacency
for router in r1 r2; do
  case "$router" in
    r1) neighbor="2.2.2.2" ;;
    r2) neighbor="1.1.1.1" ;;
  esac

  attempt=0

  until docker exec "clab-ospftest-$router" vtysh -c "show ip ospf neighbor" | grep -Eq "^[[:space:]]*${neighbor}[[:space:]].*Full/"; do
    attempt=$((attempt + 1))

    if [ "$attempt" -ge 45 ]; then
      echo "ERROR: OSPF neighbor is not FULL on $router" >&2
      exit 1
    fi

    sleep 2
  done

  echo "OSPF neighbor FULL verified on $router."
done
# Provision the restricted SSH evidence-collection account.
sh scripts/provision_readonly_ssh.sh
echo "Deployment and configuration restore completed."
