# Copyright 2019 Kaloom, Inc.  All rights reserved.
# Copyright (C) 2011 Midokura KK
# Copyright (C) 2011 Nicira, Inc
# Copyright 2011 OpenStack Foundation
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
from oslo_log import log as logging

from os_vif import objects
from os_vif import plugin
from oslo_config import cfg

from vif_plug_kaloom_kvs import constants
from vif_plug_kaloom_kvs import kvs_net

'''
## using "agent_rpc and common_rpc" are giving ERROR stevedore.extension [-] Could not load 'ovs': duplicate option: host
## need to fix TODO
## for now MAC entry not deleted
from neutron.agent import rpc as agent_rpc
from neutron.common import rpc as common_rpc
from neutron_lib import context as _context
import oslo_messaging
'''
LOG = logging.getLogger(__name__)

'''
class kvsPluginApi(agent_rpc.PluginApi):
    def __init__(self, topic):
        target = oslo_messaging.Target(topic=topic, version='1.0')
        self.client = common_rpc.get_client(target)

    def get_knid(self, context, network_id):
        cctxt = self.client.prepare()
        LOG.info("vif plug: RPC get_knid is called for network_id: %s.", network_id)
        return cctxt.call(context, 'get_knid', network_id=network_id)
'''

class KaloomKVSPlugin(plugin.PluginBase):
    """An Kaloom plugin that can setup VIFs on Kaloom KVS.

    The kaloom plugin supports several different VIF types, VIFBridge
    and VIFKaloom, and will choose the appropriate plugging
    action depending on the type of VIF config it receives.

    If given a VIFBridge, then it will connect the VM via
    a regular Linux bridge device to allow security group rules to
    be applied to VM traffic and then connects to kaloom KVS. 

    If given a VIFKaloom, then it will connect the VM directly to
    to kaloom KVS. 
    """

    CONFIG_OPTS = (
        cfg.IntOpt('network_device_mtu',
                   default=1500,
                   help='MTU setting for network interface.',
                   deprecated_group="DEFAULT"),
        cfg.IntOpt('kvs_timeout',
                   default=120,
                   help='Amount of time, in seconds, that kvs grpc should '
                   'wait for a response from the grpc server. 0 is to wait '
                   'forever.',
                   deprecated_group="DEFAULT"),
    )

    def describe(self):
        pp_ovs = objects.host_info.HostPortProfileInfo(
            profile_object_name=
            objects.vif.VIFPortProfileOpenVSwitch.__name__,
            min_version="1.0",
            max_version="1.0",
        )
        pp_ovs_representor = objects.host_info.HostPortProfileInfo(
            profile_object_name=
            objects.vif.VIFPortProfileOVSRepresentor.__name__,
            min_version="1.0",
            max_version="1.0",
        )

        return objects.host_info.HostPluginInfo(
            plugin_name=constants.PLUGIN_NAME,
            vif_info=[
                objects.host_info.HostVIFInfo(
                    vif_object_name=objects.vif.VIFVHostUser.__name__,
                    min_version="1.0",
                    max_version="1.0",
                    supported_port_profiles=[pp_ovs, pp_ovs_representor]),
            ])



    @staticmethod
    def gen_port_name(prefix, id):
        return ("%s%s" % (prefix, id))

    def _get_mtu(self, vif):
        if vif.network and vif.network.mtu:
            return vif.network.mtu
        return self.config.network_device_mtu

    def _plug_vhostuser(self, vif, instance_info):
        if vif.mode == "client":
              mtu = self._get_mtu(vif)
              kvs_net.create_kvs_vhost_port(vif.path, vif.address, mtu)
        else:
              LOG.error("vhost mode %s not supported", vif.mode)

    def _unplug_vhostuser(self, vif, instance_info):
        if vif.mode == "client":
            '''
            self.kvs_rpc = kvsPluginApi(constants.TOPIC_KNID)
            context = _context.get_admin_context_without_session()
            result = self.kvs_rpc.get_knid(context, vif.network.id)
            LOG.info("_unplug_vhostuser rpc get_knid called %s", result)
            if constants.KVS_KNID not in result:
                LOG.error("_unplug_vhostuser rpc get_knid failed result: %s", result)
            else:
                knid = result[constants.KVS_KNID]
                kvs_net.delete_mac_entry(knid, vif.address)
            '''
            kvs_net.delete_kvs_port(vif.path)
        else:
              LOG.error("vhost mode %s not supported", vif.mode)


    def plug(self, vif, instance_info):
        LOG.info('vif %(vif)s instance_info %(instance)s', {"vif":vif, "instance":instance_info})

        if isinstance(vif, objects.vif.VIFVHostUser):
            self._plug_vhostuser(vif, instance_info)
        

    def unplug(self, vif, instance_info):
        if isinstance(vif, objects.vif.VIFVHostUser):
            self._unplug_vhostuser(vif, instance_info)

