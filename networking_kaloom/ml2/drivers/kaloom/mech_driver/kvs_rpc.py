# Copyright 2019 Kaloom, Inc.  All rights reserved.
# (c) Copyright 2015 Hewlett Packard Enterprise Development LP
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

import time

from oslo_log import log
import oslo_messaging

from neutron_lib.plugins import directory
from neutron_lib import context as nctx
from neutron.common import rpc as common_rpc
from neutron_lib.agent import topics
from neutron import manager
from networking_kaloom.ml2.drivers.kaloom.agent.common import constants as a_const
from networking_kaloom.ml2.drivers.kaloom.db import kaloom_db
LOG = log.getLogger(__name__)


class KvsServerRpcCallback(object):
    """Plugin side of the KVS get_knid rpc.

    This class contains extra rpc callbacks to be served for use by the
    KVS Agent.
    """
    target = oslo_messaging.Target(version='1.0')

    def __init__(self, notifier=None):
        super(KvsServerRpcCallback, self).__init__()
        self.notifier = notifier

    @property
    def plugin(self):
        return manager.NeutronManager.get_plugin()

    def get_knid(self, rpc_context, **kwargs):
        """RPC for getting knid info.
        """
        network_id = kwargs.get('network_id')
        knid = kaloom_db.get_knid_for_network(network_id)
        result = {a_const.KVS_KNID: knid}
        LOG.info("get_knid rpc get called: network_id: %s result: %s", network_id, result)
        return result

    def get_mac(self, rpc_context, **kwargs):
        """RPC for getting mac info.
        """
        port_id = kwargs.get('port_id')
        mac = kaloom_db.get_mac_for_port(port_id)
        result = {}
        if mac is not None:
            result = {a_const.KVS_MAC: mac}
        LOG.info("get_mac rpc get called: port_id: %s result: %s", port_id, result)
        return result

    def _get_parent_port_info(self, trunk_id):
        ctx = nctx.get_admin_context()
        try:
           port_id = directory.get_plugin('trunk').get_trunk(ctx, trunk_id)['port_id']
           mac = directory.get_plugin().get_port(ctx, port_id)['mac_address']
           return port_id, mac
        except Exception as e:
           msg = "_get_parent_port_info failed: %s" % (e)
           LOG.error(msg)
           return None, None

    def get_parent_port_info(self, rpc_context, **kwargs):
        """RPC for getting parent_port_id and mac of trunk_id.
        """
        trunk_id = kwargs.get('trunk_id')
        port_id, mac = self._get_parent_port_info(trunk_id) 
        result = {}
        if port_id is not None:
            result = {a_const.KVS_PARENT_PORT_ID: port_id, a_const.KVS_MAC : mac}
        LOG.info("get_parent_port_info rpc get called: trunk_id: %s result: %s", trunk_id, result)
        return result

    def _get_ip_mac_pairs(self, port_details):
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
        return pairs

    def _get_info_port(self, port_id):
        ctx = nctx.get_admin_context()
        try:
           port = directory.get_plugin().get_port(ctx, port_id)
           pairs = self._get_ip_mac_pairs(port)
           return port['network_id'], pairs
        except Exception as e:
           msg = "_get_info_port failed: %s" % (e)
           LOG.error(msg)
           return None, []

    def get_info_sub_port(self, rpc_context, **kwargs):
        """RPC for getting knid,ip,mac info of sub port_ids.
        """
        port_ids = kwargs.get('port_ids')
        result={}
        for port_id in port_ids:
           result[port_id] = {'knid': None, 'pairs': []} 
           network_id, pairs = self._get_info_port(port_id)
           if network_id is not None:
              knid = kaloom_db.get_knid_for_network(network_id)
              result[port_id] = {'knid': knid, 'pairs': pairs} 
        LOG.info("get_info_sub_port rpc get called: result: %s", result)
        return result

class KvsAgentNotifyAPI(object):
    """Agent side of the rpc"""

    def __init__(self, topic=topics.AGENT):
        target = oslo_messaging.Target(topic=topic, version='1.0')
        self.client = common_rpc.get_client(target)
        self.topic = topic
