# Copyright 2019 Kaloom, Inc.  All rights reserved.
# Copyright 2014 Arista Networks, Inc.  All rights reserved.
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

import hashlib
import socket
import struct
import netaddr

from neutron_lib import constants as const
from oslo_config import cfg
from oslo_log import log as logging

from networking_kaloom.ml2.drivers.kaloom.common.kaloom_netconf import KaloomNetconf
from networking_kaloom.services.l3 import exceptions as kaloom_exc

LOG = logging.getLogger(__name__)

IPV4_BITS = 32
IPV6_BITS = 128

class KaloomL3Driver(object):
    """Wraps Kaloom vFabric Netconf.

    All communications between Neutron and vFabric are over Netconf.
    """
    def __init__(self, prefix):
        self.kaloom = KaloomNetconf(cfg.CONF.KALOOM.kaloom_host,
                                    cfg.CONF.KALOOM.kaloom_port,
                                    cfg.CONF.KALOOM.kaloom_username,
                                    cfg.CONF.KALOOM.kaloom_private_key_file,
                                    cfg.CONF.KALOOM.kaloom_password)
        self._enable_cleanup = cfg.CONF.KALOOM.enable_cleanup
        self.prefix = prefix

    def do_cleanup(self):
        routers =  self.kaloom.list_router_name_id()
        LOG.info('do_cleanup: list of routers %s', routers)
        for (router_name, router_node_id) in routers:
            if router_name.startswith(self.prefix):
               try:
                  self.kaloom.delete_router(router_node_id)
               except:
                  pass
    def router_exists(self, context, router):
        """checks if given router exists or not in Kaloom vFabric"""
        if router:
            router_name = self._kaloom_router_name(router['id'],
                                                   router['name'])
            try:
                vfabric_router_id = self.kaloom.get_router_id_by_name(router_name)
                if vfabric_router_id is None:
                    return False
                else:
                    return True

            except Exception:
                msg = (_('Failed to check router %s on Kaloom vFabric') %
                       router_name)
                LOG.exception(msg)
                raise kaloom_exc.KaloomServicePluginRpcError(msg=msg)


    def create_router(self, context, router):
        """Creates a router on Kaloom vFabric.
        """
        if router:
            router_name = self._kaloom_router_name(router['id'],
                                                   router['name'])

            try:
                LOG.info('Trying to create_router %s in vfabric', router_name)
                self.kaloom.create_router(router_name)
            except Exception:
                msg = (_('Failed to create router %s on Kaloom vFabric') %
                         router_name)
                LOG.exception(msg)
                raise kaloom_exc.KaloomServicePluginRpcError(msg=msg)

    def delete_router(self, context, router_id, router):
        """Deletes a router from Kaloom vFabric."""
        if router:
            router_name = self._kaloom_router_name(router_id, router['name'])
            try:
                LOG.info('Trying to delete_router %s in vfabric', router_name)
                vfabric_router_id = self.kaloom.get_router_id_by_name(router_name)
                if vfabric_router_id is None:
                    LOG.warning('No such vfabric router=%s to delete', router_name)
                    return 

                self.kaloom.delete_router(vfabric_router_id)
            except Exception:
                msg = (_('Failed to delete router %s on Kaloom vFabric') %
                       router_name)
                LOG.exception(msg)
                raise kaloom_exc.KaloomServicePluginRpcError(msg=msg)

    def update_router(self, context, router_id, original_router, new_router):
        """Updates a router which is already created on Kaloom vFabric.
        """
        ori_router_name = self._kaloom_router_name(router_id, original_router['name'])
        new_router_name = self._kaloom_router_name(router_id, new_router['name'])
        try:
            LOG.info('Trying to rename vfabric router %s to %s', ori_router_name, new_router_name)
            vfabric_router_id = self.kaloom.get_router_id_by_name(ori_router_name)
            if vfabric_router_id is None:
                msg = "non-existing vfabric router"
                raise kaloom_exc.KaloomServicePluginRpcError(msg=msg)

            router_info={'router_node_id': vfabric_router_id, 'router_name': new_router_name}
            self.kaloom.rename_router(router_info)
        except Exception:
            msg = (_('Failed to rename vFabric router %s to %s') % (ori_router_name, new_router_name))
            LOG.exception(msg)
            raise kaloom_exc.KaloomServicePluginRpcError(msg=msg)

    def update_router_routes_info(self, context, router_id, original_router, new_routes_info):
        """ Updates a router's extra-routes as new_routes_info on Kaloom vFabric.
        """
        if original_router:
            router_name = self._kaloom_router_name(router_id, original_router['name'])
            try:
                LOG.info('Trying to update routes %s on vfabric router %s', new_routes_info, router_name)
                vfabric_router_id = self.kaloom.get_router_id_by_name(router_name)
                if vfabric_router_id is None:
                    msg = "non-existing vfabric router"
                    raise kaloom_exc.KaloomServicePluginRpcError(msg=msg)

                original_routes_info = original_router['routes'] 

                #Find diff
                new_set = set()
                for new_route in new_routes_info:
                    new_set.add((new_route["destination"],new_route["nexthop"]))

                original_set = set()
                for original_route in original_routes_info:
                    original_set.add((original_route["destination"],original_route["nexthop"]))

                setup = new_set - original_set
                delete = original_set - new_set

                for (destination, nexthop) in setup:
                    route_info={'router_node_id': vfabric_router_id, 'destination_prefix': destination, 'next_hop_address': nexthop}
                    route_info['ip_version'] = netaddr.IPNetwork(destination.split('/')[0]).version
                    self.kaloom.add_ip_static_route(route_info)

                for (destination, nexthop) in delete:
                    route_info = {'router_node_id': vfabric_router_id, 'destination_prefix': destination}
                    route_info['ip_version'] = netaddr.IPNetwork(destination.split('/')[0]).version
                    self.kaloom.delete_ip_static_route(route_info)

            except Exception:
                msg = (_('Failed to update routes %s on vfabric router '
                       '%s') % (new_routes_info, router_name))
                LOG.exception(msg)
                raise kaloom_exc.KaloomServicePluginRpcError(msg=msg)

    def router_l2node_link_exists(self, router_id, name, l2_node_id):
        """ check the link between router and l2_node exists or not. 
        """
        if router_id:
            router_name = self._kaloom_router_name(router_id, name)
            try:
                router_inf_info = self.kaloom.get_router_interface_info(router_name, l2_node_id)
                vfabric_router_id = router_inf_info['node_id']
                tp_interface_name = router_inf_info['interface']
                if vfabric_router_id is not None and tp_interface_name is not None:
                    return True
                else:
                    return False
            except Exception:
                msg = (_('Failed to check router--l2_node %s--%s link existence on Kaloom vFabric') %
                       (router_name, l2_node_id))
                LOG.exception(msg)
                raise kaloom_exc.KaloomServicePluginRpcError(msg=msg)

    def add_router_interface(self, context, router_info):
        """In case of no router interface present for the network of subnet, creates the interface.
        Adds a subnet configuration to the router interface on Kaloom vFabric.
        This deals with both IPv6 and IPv4 configurations. 
        """
        if router_info:
            router_name = self._kaloom_router_name(router_info['id'],
                                                   router_info['name'])
            l2_node_id = router_info['nw_name']
            try:
                LOG.info('Trying to add subnet %s to vfabric router %s -- network %s', router_info['subnet_id'], router_name, l2_node_id)
                router_inf_info = self.kaloom.get_router_interface_info(router_name, l2_node_id)
                vfabric_router_id = router_inf_info['node_id']
                tp_interface_name = router_inf_info['interface']
                if vfabric_router_id is None:
                    msg = "non-existing vfabric router"
                    raise kaloom_exc.KaloomServicePluginRpcError(msg=msg)

                ## first subnet request ? absence of router--l2_node interface, first create interface.
                if tp_interface_name is None:
                    tp_interface_name = self.kaloom.attach_router(vfabric_router_id, l2_node_id)

                #add_ipaddress_to_interface
                interface_info={}
                interface_info['router_node_id'] = vfabric_router_id
                interface_info['interface_name'] = tp_interface_name
                interface_info['ip_version'] = router_info['ip_version']
                interface_info['ip_address'] = router_info['ip_address']
                interface_info['prefix_length'] = router_info['cidr'].split('/')[1]
                try:
                    self.kaloom.add_ipaddress_to_interface(interface_info)
                except Exception as e:
                    msg = "add_ipaddress_to_interface failed: %s" % (e)
                    LOG.exception(msg)
                    self.remove_router_interface(context, router_info)
                    raise kaloom_exc.KaloomServicePluginRpcError(msg=msg)
            except Exception:
                msg = (_('Failed to add subnet %s to vfabric router '
                       '%s -- network %s') % (router_info['subnet_id'], router_name, l2_node_id))
                LOG.exception(msg)
                raise kaloom_exc.KaloomServicePluginRpcError(msg=msg)

    def remove_router_interface(self, context, router_info):
        """Removes previously configured subnet interface from router on Kaloom vFabric.
        This deals with both IPv6 and IPv4 configurations. In case of no more subnet configuration remained, 
        removes interface connected to network. 
        """
        if router_info:
            router_name = self._kaloom_router_name(router_info['id'],
                                                   router_info['name'])
            l2_node_id = router_info['nw_name']
            try:
                LOG.info('Trying to remove subnet %s from vfabric router %s -- network %s', router_info['subnet_id'], router_name, l2_node_id)
                router_inf_info = self.kaloom.get_router_interface_info(router_name, l2_node_id)
                vfabric_router_id = router_inf_info['node_id']
                tp_interface_name = router_inf_info['interface']
                count_ip = len(router_inf_info['ip_addresses'])

                if vfabric_router_id is None:
                    LOG.warning('no router_interface to remove on non-existing vfabric router=%s', router_name)
                    return
 
                if tp_interface_name is None:
                    LOG.warning('no router_interface to remove on router=%s', router_name)
                    return

                if count_ip <= 1: #last IP subnet remained, detach router
                    self.kaloom.detach_router(vfabric_router_id, l2_node_id)
                else:
                    #delete_ipaddress_from_interface
                    interface_info={}
                    interface_info['router_node_id'] = vfabric_router_id
                    interface_info['interface_name'] = tp_interface_name
                    interface_info['ip_version'] = router_info['ip_version']
                    interface_info['ip_address'] = router_info['ip_address']
                    self.kaloom.delete_ipaddress_from_interface(interface_info)
            except Exception as e:
                msg = (_('Failed to remove subnet %s from vfabric router '
                    '%s -- network %s, msg: %s') % (router_info['subnet_id'], router_name, l2_node_id, e))
                LOG.exception(msg)
                raise kaloom_exc.KaloomServicePluginRpcError(msg=msg)

    def _kaloom_router_name(self, router_id, name):
        """Generate an kaloom specific name for this router.

        Use a unique name so that OpenStack created routers
        can be distinguishged from the user created routers
        on Kaloom vFabric. Replace spaces with underscores for CLI compatibility
        """
        return self.prefix + router_id + '.' + name.replace(' ', '_')
