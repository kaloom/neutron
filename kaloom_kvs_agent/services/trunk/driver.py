# Copyright 2019 Kaloom, Inc.  All rights reserved.
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
from neutron_lib.callbacks import events as local_events
from neutron_lib.callbacks import registry as local_registry
from neutron_lib.callbacks import resources as local_resources
from oslo_log import log as logging
import oslo_messaging
from oslo_config import cfg
import os 
import netaddr
from neutron.api.rpc.callbacks.consumer import registry
from neutron.api.rpc.callbacks import events
from neutron.api.rpc.callbacks import resources
from neutron.api.rpc.handlers import resources_rpc
from neutron_lib.services.trunk import constants
from neutron.services.trunk.rpc import agent

from kaloom_kvs_agent.common \
    import utils as kvs_utils

from kaloom_kvs_agent.common \
     import constants as a_const

from kaloom_kvs_agent \
    import kvs_net

from kaloom_kvs_agent.common \
     import config as kaloom_config

LOG = logging.getLogger(__name__)

class _TrunkAPI(object):
    def __init__(self, trunk_stub):
        self.server_api = trunk_stub

    def get_trunk(self, context, port_id):
        try:
            t = self.server_api.get_trunk_details(context, port_id)
            LOG.debug("Found trunk %(t)s for port %(p)s", dict(p=port_id, t=t))
            return t
        except resources_rpc.ResourceNotFound:
            return None
        except oslo_messaging.RemoteError as e:
            if e.exc_type != 'CallbackNotFound':
                raise
            LOG.debug("Trunk plugin disabled on server. Assuming port %s is "
                      "not a trunk.", port_id)
            return None
    def set_trunk_status(self, context, trunk_id, status):
        self.server_api.update_trunk_status(context, trunk_id, status)


@local_registry.has_registry_receivers
class KVSTrunkSkeleton(agent.TrunkSkeleton):
    """It processes Neutron Server events to create the physical resources
    associated to a logical trunk in response to user initiated API events
    (such as trunk subport add/remove). It collaborates with the KVS to 
    implement the trunk control plane.
    """
    def __init__(self):
        super(KVSTrunkSkeleton, self).__init__()
        registry.unsubscribe(self.handle_trunks, resources.TRUNK)
        self._tapi = _TrunkAPI(agent.TrunkStub())
        self.kvs_rpc = kvs_utils.kvsPluginApi(a_const.TOPIC_KNID)
        kaloom_config.register_kaloomkvs_opts()
        self.vhostuser_socket_dir = cfg.CONF.kaloom_kvs.vhostuser_socket_dir

    def _get_vhost_path(self, port_id):
        sock_name = (a_const.KVS_VHOSTUSER_PREFIX + port_id)
        vhost_path = os.path.join(self.vhostuser_socket_dir, sock_name)
        return vhost_path

    def _manages_this_trunk(self, context, trunk_id):
        result = self.kvs_rpc.get_parent_port_info(context, trunk_id)
        LOG.info("rpc get_parent_port_info called %s", result)
        if a_const.KVS_PARENT_PORT_ID not in result:
            LOG.error("rpc get_parent_port_info failed result: %s", result)
            return None
        parent_port_id = result[a_const.KVS_PARENT_PORT_ID]
        ports = kvs_net.listPorts(self.vhostuser_socket_dir, a_const.KVS_VHOSTUSER_PREFIX)
        if parent_port_id in ports.keys():
            parent_port_info =  {} 
            parent_port_info['kvs_device_name'] = self._get_vhost_path(parent_port_id)
            parent_port_info['kvs_port_id'] = ports[parent_port_id]
            parent_port_info['mac'] = result[a_const.KVS_MAC]
            return parent_port_info
        return None

    def _dhcp_discover_rule_pairs(self, pairs, mac):
        ipv4_addresses = {pair["ip"] for pair in pairs
                 if netaddr.IPNetwork(pair["ip"]).version == 4}

        ipv6_addresses = {pair["ip"] for pair in pairs
                 if netaddr.IPNetwork(pair["ip"]).version == 6}

        new_pairs=[]
        ##allow "dhcp discover/solicit" through kvs
        if len(ipv4_addresses) > 0:
            pair = {"ip": "0.0.0.0", "mac": mac}
            new_pairs.append(pair)

        if len(ipv6_addresses) > 0:
            pair = {"ip": kvs_utils.mac2ipv6(mac), "mac": mac}
            new_pairs.append(pair)

        return new_pairs

    def handle_trunks(self, context, resource_type, trunk, event_type):
        """This method is not required by the KVS Agent driver.
        """
        LOG.info("handle_trunks get called trunk: %s , event_type: %s", trunk, event_type)
        raise NotImplementedError()

    @local_registry.receives(local_resources.PORT_DEVICE,
                       [local_events.AFTER_DELETE])
    # def agent_port_delete(self, resource, event, trigger, context, port_id,**kwargs):
    def agent_port_delete(self, resource, event, trigger, payload=None):

        """Agent informed us a VIF was removed."""
        #LOG.info("Trunk driver receives: agent port delete: port_id %s", port_id)
        #nothing to do: port_delete already deleted port and multiple attachment, anti-spoofing, static-mac. 
        pass

    @local_registry.receives(local_resources.PORT_DEVICE,
                       [local_events.AFTER_UPDATE])
    # def agent_port_change(self, resource, event, trigger, context,device_details, **kwargs):
    def agent_port_change(self, resource, event, trigger, payload=None):
        """The agent has informed us a port update or create."""
        # check if the port has trunk_details, if yes plumb subports
        # port_id = device_details['port_id']
        port_id = payload.latest_state['port_id']
        # trunk = self._tapi.get_trunk(context, port_id)
        trunk = self._tapi.get_trunk(payload.context, port_id)
        if trunk is not None:
            LOG.info("Trunk driver receives agent's trunk port_id %s event %s", port_id, event)
            if len(trunk.sub_ports)>0:
                #use existing function to handle subports
                # self.handle_subports(context,'',trunk.sub_ports, events.CREATED)
                self.handle_subports(payload.context, '',
                                     trunk.sub_ports, events.CREATED)

    def handle_subports(self, context, resource_type, subports, event_type):
        # Subports are always created with the same trunk_id and there is
        # always at least one item in subports list
        trunk_id = subports[0].trunk_id

        parent_port_info = self._manages_this_trunk(context, trunk_id)
        if parent_port_info is None:
            LOG.info("The trunk %s is not managed by this host/agent", trunk_id)
        else:
            if event_type not in (events.CREATED, events.DELETED):
                LOG.error("Unknown or unimplemented event %s", event_type)
                return

            try:
                kvs_port_id = parent_port_info['kvs_port_id']
                LOG.debug("Event %s for subports: %s", event_type, subports)
                subport_ids = [subport.port_id for subport in subports]
                result = self.kvs_rpc.get_info_sub_port(context, subport_ids)
                if event_type == events.CREATED:
                    LOG.info("event CREATED: trunk_id %s, subports %s ", trunk_id, subports)
                    for subport in subports:
                        vlan = subport.segmentation_id
                        knid = result[subport.port_id]['knid']
                        if knid is not None:
                           # add anti-spoofing rules
                           pairs = result[subport.port_id]['pairs']
                           mac = None
                           if len(pairs) > 0:
                              mac = pairs[0]['mac']
                              #we need extra dhcp discover/solicit rules
                              pairs.extend(self._dhcp_discover_rule_pairs(pairs, mac))
                              for pair in pairs:
                                 _ip = pair['ip']
                                 _mac = pair['mac']
                                 kvs_net.add_anti_spoofing_rule(kvs_port_id, _mac, _ip, vlan = vlan )
                           ## attach interface to network, with access vlan
                           kvs_net._attach_interface(parent_port_info['kvs_device_name'], kvs_port_id, knid, vlan)
                           ## add static-mac rule
                           if mac is not None:
                              kvs_net.add_mac_entry(knid, mac, kvs_port_id, vlan)
                        else:
                           LOG.error("KNID not found for trunk's subport %s", subport.port_id)
                    #update status of trunk
                    #self._tapi.set_trunk_status(context, trunk_id, constants.ACTIVE_STATUS)
                elif event_type == events.DELETED:
                    LOG.info("event DELETED: trunk_id %s, subport_ids %s ", trunk_id, subports)
                    for subport in subports:
                        vlan = subport.segmentation_id
                        knid = result[subport.port_id]['knid']
                        if knid is not None:
                           # detach interface from network
                           kvs_net._detach_interface(parent_port_info['kvs_device_name'], kvs_port_id, vlan)
                           pairs = result[subport.port_id]['pairs'] 
                           if len(pairs) > 0:
                              ## delete static-mac rule
                              mac = pairs[0]['mac']
                              kvs_net.delete_mac_entry(knid, mac)
                              # delete anti-spoofing rules
                              #we need to delete extra dhcp discover/solicit rules
                              pairs.extend(self._dhcp_discover_rule_pairs(pairs, mac))
                              for pair in pairs:
                                 ip = pair['ip']
                                 mac = pair['mac']
                                 kvs_net.delete_anti_spoofing_rule(kvs_port_id, mac, ip, vlan = vlan)

            except oslo_messaging.MessagingException as e:
                LOG.error(
                    "Error on event %(event)s for subports "
                    "%(subports)s: %(err)s",
                    {'event': event_type, 'subports': subports, 'err': e})

def init_handler(resource, event, trigger, payload=None):
    """Handler for agent init event."""
    # Set up agent-side RPC for receiving trunk events;
    LOG.debug("trunk init_handler get called")
    KVSTrunkSkeleton()

