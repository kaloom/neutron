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

LOG = logging.getLogger(__name__)

class KaloomKVSPlugin(plugin.PluginBase):
    """An Kaloom plugin that can setup VIFs on Kaloom KVS.

    The kaloom plugin supports VIF type VIFVHostUser and 
    will choose the appropriate plugging
    action depending on the type of VIF config it receives.

    If given a VIFVHostUser, then it will connect the VM directly to
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
        pp_kvs = objects.host_info.HostPortProfileInfo(
            profile_object_name=
            objects.vif.VIFPortProfileOpenVSwitch.__name__,
            min_version="1.0",
            max_version="1.0",
        )
        pp_kvs_representor = objects.host_info.HostPortProfileInfo(
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
                    supported_port_profiles=[pp_kvs, pp_kvs_representor]),
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
            #deleting port itself deletes existing static-mac entry
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

