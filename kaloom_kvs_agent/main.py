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

import sys
import eventlet
import os,errno

from neutron_lib.utils import helpers
from oslo_config import cfg
from oslo_utils import importutils
import oslo_messaging
from oslo_service import service
from oslo_log import log as logging

from neutron_lib import constants
from neutron.agent.l3 import namespaces
from neutron.agent.linux import bridge_lib
from neutron_lib import context as _context
from neutron.common import topics
from neutron.api.rpc.handlers import securitygroups_rpc as sg_rpc
from neutron.agent.linux import ip_lib
from neutron.common import config as common_config
from neutron.conf.agent import common as agent_config
from neutron.plugins.ml2.drivers.agent import _agent_manager_base as amb
from neutron.plugins.ml2.drivers.agent import _common_agent as ca
from kaloom_kvs_agent.common \
     import constants as a_const
from kaloom_kvs_agent.common \
     import config as kaloom_config
from kaloom_kvs_agent import \
    kaloomkvs_agent_extension_api as agent_extension_api
from kaloom_kvs_agent \
    import kaloomkvs_capabilities
from kaloom_kvs_agent \
    import kvs_net
from kaloom_kvs_agent.common \
    import utils as kvs_utils
from kaloom_kvs_agent \
    import arp_protect


from neutron.common import profiler as setup_profiler

LOG = logging.getLogger(__name__)

IPTABLES_DRIVERS = [
    'iptables',
    'iptables_hybrid',
    'neutron.agent.linux.iptables_firewall.IptablesFirewallDriver',
    'neutron.agent.linux.iptables_firewall.OVSHybridIptablesFirewallDriver'
]

class KaloomKVSManager(amb.CommonAgentManagerBase):
    def __init__(self,bridge_mappings,kvs_id,vhostuser_socket_dir):
        super(KaloomKVSManager, self).__init__()
        self.bridge_mappings = bridge_mappings
        self.interface_mappings ={}
        self.validate_interface_mappings()
        self.vhostuser_socket_dir=vhostuser_socket_dir
        self.kvs_id=kvs_id
        self.ip = ip_lib.IPWrapper()
        self.agent_api = None

    def validate_interface_mappings(self):
        pass

    def get_vhost_path(self,port_id):
        sock_name = (a_const.KVS_VHOSTUSER_PREFIX + port_id)
        vhost_path= os.path.join(self.vhostuser_socket_dir, sock_name)
        return vhost_path

    @staticmethod
    def get_tap_device_name(interface_id):
        return kvs_utils.get_tap_device_name(interface_id)

    def plug_interface(self, network_id, network_segment, device_name,
                       device_owner):   
        LOG.info("KaloomKVSManager plug_interface called ")

        self.kvs_rpc = kvs_utils.kvsPluginApi(a_const.TOPIC_KNID)
        context = _context.get_admin_context_without_session()
        result = self.kvs_rpc.get_knid(context, network_id)
        LOG.info("KaloomKVSManager rpc get_knid called %s", result)
        if a_const.KVS_KNID not in result:
              LOG.error("KaloomKVSManager rpc get_knid failed result: %s", result)
              return False

        knid = result[a_const.KVS_KNID]

        if device_name.startswith(constants.TAP_DEVICE_PREFIX):
           kvs_device_name = device_name
        elif device_owner == "network:router_gateway":
           kvs_device_name = namespaces.EXTERNAL_DEV_PREFIX + device_name
        elif device_owner == "network:router_interface":
           kvs_device_name = namespaces.INTERNAL_DEV_PREFIX + device_name
        else:
           kvs_device_name = self.get_vhost_path(device_name)

        success, port_index = kvs_net.attach_interface(network_id, network_segment.network_type,
                                      network_segment.physical_network,
                                      knid,
                                      kvs_device_name, device_owner,
                                      network_segment.mtu,
                                      self.vhostuser_socket_dir, a_const.KVS_VHOSTUSER_PREFIX)
        #adding mac entry only for vhostuser interface
        #not required for vdev interface
        if not kvs_device_name.startswith((constants.TAP_DEVICE_PREFIX, namespaces.INTERNAL_DEV_PREFIX, namespaces.EXTERNAL_DEV_PREFIX)) and success is True:
             result = self.kvs_rpc.get_mac(context, device_name)
             if a_const.KVS_MAC in result:
                 mac = result[a_const.KVS_MAC]
                 LOG.info("KaloomKVSManager rpc get_mac called %s", result)
                 return kvs_net.add_mac_entry(knid, mac, port_index)
             else:
                 LOG.error("KaloomKVSManager rpc get_mac failed result: %s", result)
                 return False
        else:
             return success

    def _convert_ns_dev_to_partial_portid(self,_ports):
        ports = {}
        for _dev_name in _ports.keys():
           if _dev_name.startswith((namespaces.INTERNAL_DEV_PREFIX, namespaces.EXTERNAL_DEV_PREFIX)):
                 dev_name = _dev_name.replace(namespaces.INTERNAL_DEV_PREFIX, "")
                 dev_name = dev_name.replace(namespaces.EXTERNAL_DEV_PREFIX, "")
                 ports[dev_name] = _ports[_dev_name]
           else:
                 ports[_dev_name] = _ports[_dev_name]
        return ports

    def get_devices_modified_timestamps(self, devices):
        _ports=kvs_net.listPorts(self.vhostuser_socket_dir, a_const.KVS_VHOSTUSER_PREFIX)
        ports = self._convert_ns_dev_to_partial_portid(_ports)
        timestamps={}
        for d in devices:
           if d in ports.keys():
              timestamps[d]=ports[d]
        LOG.debug("KaloomKVSManager get_devices_modified_timestamps %s",timestamps)
        return timestamps

    def get_all_devices(self):
        devices = set()
        _ports=kvs_net.listPorts(self.vhostuser_socket_dir, a_const.KVS_VHOSTUSER_PREFIX)
        ports = self._convert_ns_dev_to_partial_portid(_ports)
        for name in ports.keys():
           devices.add(name)
        LOG.debug("KaloomKVSManager get_all_devices %(devices)s ", {"devices" : devices})
        return devices


    def get_agent_id(self):
        if self.kvs_id is None:
            LOG.error("Unable to obtain unique ID. "
                      "Agent terminated!")
            sys.exit(1)
        return self.kvs_id


    def get_agent_configurations(self):
        configurations = {'bridge_mappings': self.bridge_mappings,
                          'interface_mappings': self.interface_mappings,
                          'vhostuser_socket_dir':self.vhostuser_socket_dir
                         }
        return configurations

    def get_rpc_callbacks(self, context, agent, sg_agent):
        return KaloomKVSRpcCallbacks(context, agent, sg_agent)

    def get_agent_api(self, **kwargs):
        if self.agent_api:
            return self.agent_api
        sg_agent = kwargs.get("sg_agent")
        iptables_manager = self._get_iptables_manager(sg_agent)
        self.agent_api = agent_extension_api.KaloomKVSAgentExtensionAPI(
            iptables_manager)
        return self.agent_api

    def _get_iptables_manager(self, sg_agent):
        if sg_agent is None:
            return None
        if cfg.CONF.SECURITYGROUP.firewall_driver in IPTABLES_DRIVERS:
            return sg_agent.firewall.iptables

    def get_rpc_consumers(self):
        consumers = [[topics.PORT, topics.UPDATE],
                     [topics.NETWORK, topics.DELETE],
                     [topics.NETWORK, topics.UPDATE],
                     [topics.SECURITY_GROUP, topics.UPDATE]]
        return consumers

    def ensure_port_admin_state(self, device_name, admin_state_up):
        LOG.info("Setting admin_state_up to %s for device %s",
                  admin_state_up, device_name)
        #admin_state is not supported for vhost interface in KVS gRPC.
        #vhost_path = self.get_vhost_path(device_name) 
        #kvs_net.configurePort(vhost_path, admin_state_up)

    def setup_arp_spoofing_protection(self, device, device_details):
        arp_protect.setup_arp_spoofing_protection(device, device_details, self.vhostuser_socket_dir)

    def delete_arp_spoofing_protection(self, devices):
        arp_protect.delete_arp_spoofing_protection(devices, self.vhostuser_socket_dir)

    def delete_unreferenced_arp_protection(self, current_devices):
        arp_protect.delete_unreferenced_arp_protection(current_devices, self.vhostuser_socket_dir, a_const.KVS_VHOSTUSER_PREFIX)

    def get_extension_driver_type(self):
        return a_const.EXTENSION_DRIVER_TYPE

class KaloomKVSRpcCallbacks(sg_rpc.SecurityGroupAgentRpcCallbackMixin,
    amb.CommonAgentManagerRpcCallBackBase):
    target = oslo_messaging.Target(version='1.4')
    def network_delete(self, context, **kwargs):
        LOG.info("network_delete received")
        network_id = kwargs.get('network_id')
        #self.agent.mgr.delete_bridge(bridge_name)
        self.network_map.pop(network_id, None)

    def port_update(self, context, **kwargs):
        port_id = kwargs['port']['id']
        if kwargs['port']['binding:vif_type']=='vhostuser':
           device_name = port_id
        else:
           device_name = self.agent.mgr.get_tap_device_name(port_id)
        self.updated_devices.add(device_name)
        LOG.info("port_update RPC received for port: %s, translated device_name %s", port_id, device_name)

    def network_update(self, context, **kwargs):
        network_id = kwargs['network']['id']
        LOG.info("network_update message processed for network "
                  "%(network_id)s, with ports: %(ports)s",
                  {'network_id': network_id,
                   'ports': self.agent.network_ports[network_id]})
        #for port_data in self.agent.network_ports[network_id]:
        #    self.updated_devices.add(port_data['device'])

def main():
    eventlet.monkey_patch()
    common_config.init(sys.argv[1:])
    kaloom_config.register_kaloomkvs_opts()
    common_config.setup_logging()
    agent_config.setup_privsep()

    try:
        bridge_mappings = helpers.parse_mappings(
            cfg.CONF.kaloom_kvs.bridge_mappings)
    except ValueError as e:
        LOG.error("Parsing bridge_mappings failed: %s. "
                  "Agent terminated!", e)
        sys.exit(1)
    LOG.info("Bridge mappings: %s", bridge_mappings)

    try:
        vhostuser_socket_dir = cfg.CONF.kaloom_kvs.vhostuser_socket_dir
    except ValueError as e:
        LOG.error("Parsing vhostuser_socket_dir failed: %s. "
                  "Agent terminated!", e)
        sys.exit(1)
    LOG.info("vhostuser_socket_dir: %s", vhostuser_socket_dir)

    dir_exists = os.path.exists(vhostuser_socket_dir)
    if dir_exists is False:
        #creating the dir with right selinux context is not preferred.
        #the dir should be pre-configured. 
        LOG.error("vhostuser_socket_dir %s does not exists."
                  "Agent terminated!", vhostuser_socket_dir)
        sys.exit(1)

    # is it compliance with permission
    status, msg = kvs_utils.check_permission(vhostuser_socket_dir)
    if status is not True:
        LOG.error("%s. Agent terminated!", msg)
        sys.exit(1)

    host = cfg.CONF.host
    kvs_id ='kvs-agent-%s' % host

    manager = KaloomKVSManager(bridge_mappings,kvs_id,vhostuser_socket_dir)
    kaloomkvs_capabilities.register()

    polling_interval = cfg.CONF.AGENT.polling_interval
    quitting_rpc_timeout = cfg.CONF.AGENT.quitting_rpc_timeout
 
    LOG.info("polling_interval: %s", polling_interval)
    LOG.info("quitting_rpc_timeout: %s", quitting_rpc_timeout)

 
    agent = ca.CommonAgentLoop(manager, polling_interval, quitting_rpc_timeout,
                               a_const.AGENT_TYPE_KALOOM_KVS,
                               a_const.KVS_AGENT_BINARY)
    setup_profiler.setup("neutron-kaloom-agent", cfg.CONF.host)
    LOG.info("Agent initialized successfully, now running... ")
    launcher = service.launch(cfg.CONF, agent)
    launcher.wait()
