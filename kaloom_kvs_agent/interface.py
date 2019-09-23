# Copyright 2019 Kaloom, Inc.  All rights reserved.
# Copyright 2012 OpenStack Foundation
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

from oslo_log import log as logging
from neutron.agent.linux import ip_lib
from neutron.common import exceptions
from neutron.agent.linux.interface import LinuxInterfaceDriver
from kaloom_kvs_agent \
    import kvs_net

LOG = logging.getLogger(__name__)

def _get_veth(name, namespace):
    if namespace == None:
       return (ip_lib.IPDevice(name))
    else:
       return (ip_lib.IPDevice(name, namespace=namespace))


class KVSInterfaceDriver(LinuxInterfaceDriver):
    """Driver for creating KVS interfaces."""

    def set_ns(self,ip, name, namespace=None):
        if namespace is None:
            namespace = ip.namespace
        else:
            ip.ensure_namespace(namespace)

        device = _get_veth(name, namespace=None)
        device.link.set_netns(namespace)
        return(_get_veth(name, namespace))


    def plug_new(self, network_id, port_id, device_name, mac_address,
                 bridge=None, namespace=None, prefix=None, mtu=None):
        """Plugin the interface."""
        ip = ip_lib.IPWrapper()

        #create kvs port: port add vdev device_name mtu <mtu> mac <52:54:00:44:f2:44>
        success = kvs_net.create_kvs_vdev_port(device_name, mac_address, mtu)
        if success is True:
             # Create ns_veth in a namespace if one is configured.
             ns_veth = self.set_ns(ip,device_name, namespace)
             ns_veth.link.set_up()

    def unplug(self, device_name, bridge=None, namespace=None, prefix=None):
        """Unplug the interface."""
        success = kvs_net.delete_kvs_port(device_name)
        if success is True:
            LOG.info("Unplugged interface '%s'", device_name)
        else:
            LOG.error("Failed unplugging interface '%s'",
                      device_name)

    def set_mtu(self, device_name, mtu, namespace=None, prefix=None):
        ns_dev = _get_veth(device_name, namespace)
        ns_dev.link.set_mtu(mtu)

