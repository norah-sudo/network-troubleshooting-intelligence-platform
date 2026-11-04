#!/bin/sh
set -eu

restore_ip() {
  node="$1"
  address="$2"

  if ! docker exec "clab-ospftest-$node" ip addr show dev eth1 | grep -Fq "inet $address "; then
    docker exec "clab-ospftest-$node" ip addr add "$address" dev eth1
  fi
}

restore_ip hr1 192.168.10.11/24
restore_ip hr2 192.168.10.12/24
restore_ip it1 192.168.20.11/24
restore_ip it2 192.168.20.12/24

ovs-vsctl set Port sw1p1 vlan_mode=trunk trunks=10,20
ovs-vsctl set Port sw2p1 vlan_mode=trunk trunks=10,20
ovs-vsctl set Port sw1p2 vlan_mode=access tag=10
ovs-vsctl set Port sw2p2 vlan_mode=access tag=10
ovs-vsctl set Port sw1p3 vlan_mode=access tag=20
ovs-vsctl set Port sw2p3 vlan_mode=access tag=20

ovs-vsctl set Port sw1p4 vlan_mode=trunk trunks=10,20
ovs-vsctl set Port sw2p4 vlan_mode=trunk trunks=10,20

echo "Network configuration restored successfully."
