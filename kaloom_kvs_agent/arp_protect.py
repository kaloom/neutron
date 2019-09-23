# Copyright 2019 Kaloom, Inc.  All rights reserved.
# Copyright (c) 2015 Mirantis, Inc.
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import netaddr
import os
from neutron_lib.utils import net
from oslo_log import log as logging
from neutron_lib import constants
from kaloom_kvs_agent \
     import kvs_net
from kaloom_kvs_agent.common \
     import constants as a_const
from kaloom_kvs_agent.common \
    import utils as kvs_utils

LOG = logging.getLogger(__name__)

def get_vhost_path(port_id, socket_dir):
    sock_name = (a_const.KVS_VHOSTUSER_PREFIX + port_id)
    vhost_path = os.path.join(socket_dir, sock_name)
    return vhost_path

def get_kvs_device_name_port_index(device_name, socket_dir):
    if device_name.startswith(constants.TAP_DEVICE_PREFIX) or len(device_name) > 15:
        if device_name.startswith(constants.TAP_DEVICE_PREFIX):
             kvs_device_name = device_name
        else:
             kvs_device_name = get_vhost_path(device_name, socket_dir)
        port_index = kvs_net.getPort(kvs_device_name, socket_dir, a_const.KVS_VHOSTUSER_PREFIX)
    else:  #qr-* qg-*
        kvs_device_name, port_index = kvs_net.getPort_partialmatch(device_name, socket_dir, a_const.KVS_VHOSTUSER_PREFIX)
    return kvs_device_name,port_index

def setup_arp_spoofing_protection(vif, port_details, socket_dir):
    kvs_device_name, port_index = get_kvs_device_name_port_index(vif, socket_dir)
    LOG.info("setup_arp_spoofing_protection called: vif %s, kvs_device_name %s", vif, kvs_device_name)

    if port_index is None:
        LOG.error("setup_arp_spoofing_protection failed: port_index could "
                  "not be found for vhost/vdev %s", kvs_device_name)
        return
    if not port_details.get('port_security_enabled', True):
        # clear any previous entries related to this port
        _delete_arp_spoofing_protection(port_index)
        LOG.info("Skipping ARP spoofing rules for port '%s' because "
                 "it has port security disabled", vif)
        return
    if net.is_port_trusted(port_details):
        # clear any previous entries related to this port
        _delete_arp_spoofing_protection(port_index)
        LOG.info("Skipping ARP spoofing rules for network owned port "
                 "'%s'.", vif)
        return

    ##apply diff rules, delete extra rules
    new_pairs = _new_anti_spoofing_rules(vif, port_details, port_index)
    #Single port represents parent-port and subports in case of trunk. 
    #parent-port rules are associated with vlan=0, and subport rules are associated with other vlans.
    #Here, we should not touch/delete trunk's subports rules.
    existing_pairs = kvs_net.list_anti_spoofing_rules(port_index, vlan = 0)
    if existing_pairs is None:
        existing_pairs = []

    new_set = set()
    for new_pair in new_pairs:
        new_set.add((new_pair["ip"],new_pair["mac"]))
    existing_set = set()
    for existing_pair in existing_pairs:
        existing_set.add((existing_pair["ip"],existing_pair["mac"]))

    setup = new_set - existing_set
    delete = existing_set - new_set

    for (ip,mac) in setup:
        kvs_net.add_anti_spoofing_rule(port_index, mac, ip)
    for (ip,mac) in delete:
        kvs_net.delete_anti_spoofing_rule(port_index, mac, ip)

def has_zero_prefixlen_address(ip_addresses):
    return any(netaddr.IPNetwork(ip).prefixlen == 0 for ip in ip_addresses)

def _new_anti_spoofing_rules(vif, port_details, port_index):
    pairs = []
    mac = port_details['mac_address']
    # collect all of the addresses and cidrs that belong to the port
    for f in port_details['fixed_ips']:
        pair = {"ip": f['ip_address'], "mac": mac}
        pairs.append(pair)

    if port_details.get('allowed_address_pairs'):
        for p in port_details['allowed_address_pairs']:
            pair = {"ip": p['ip_address'], "mac": p['mac_address']}
            pairs.append(pair)

    ipv4_addresses = {pair["ip"] for pair in pairs
                 if netaddr.IPNetwork(pair["ip"]).version == 4}

    ipv6_addresses = {pair["ip"] for pair in pairs
                 if netaddr.IPNetwork(pair["ip"]).version == 6}

    if has_zero_prefixlen_address(ipv4_addresses) or has_zero_prefixlen_address(ipv6_addresses):
        # don't try to install protection because a /0 prefix allows any
        # address anyway and the ARP_SPA can only match on /1 or more.
        return [] 

    ##allow "dhcp discover/solicit" through kvs
    if len(ipv4_addresses) > 0:
        pair = {"ip": "0.0.0.0", "mac": mac}
        pairs.append(pair)

    if len(ipv6_addresses) > 0:
        pair = {"ip": kvs_utils.mac2ipv6(mac), "mac": mac}
        pairs.append(pair)

    return pairs

def delete_arp_spoofing_protection(vifs, socket_dir):
    for vif in vifs:
        kvs_device_name, port_index = get_kvs_device_name_port_index(vif, socket_dir)
        LOG.info("delete_arp_spoofing_protection called: vif %s , kvs_device_name %s", vif, kvs_device_name)

        if port_index is None:
            LOG.error("delete_arp_spoofing_protection failed: port_index could"
                      "not be found for vhost/vdev %s", kvs_device_name)
        else:
            _delete_arp_spoofing_protection(port_index)

def _delete_arp_spoofing_protection(port_index):
    # list_anti_spoofing_rule
    #Single port represents parent-port and subports in case of trunk. 
    #parent-port rules are associated with vlan=0, and subport rules are associated with other vlans.
    #Here, we want to delete all rules associated to parent-port and subports. 
    pairs = kvs_net.list_anti_spoofing_rules(port_index)
    if pairs is not None:
       for pair in pairs:
           # delete one by one
           kvs_net.delete_anti_spoofing_rule(port_index, pair['mac'], pair['ip'])


def delete_unreferenced_arp_protection(current_vifs, socket_dir, file_prefix):
    #deletes all anti_spoofing rules that aren't in current_vifs
    LOG.info("delete_unreferenced_arp_protection called with current_vifs: %s", current_vifs)
    ports = kvs_net.listPorts(socket_dir, file_prefix)
    for port_name in ports.keys():
        if port_name not in current_vifs:
            port_index = ports[port_name]
            _delete_arp_spoofing_protection(port_index)
