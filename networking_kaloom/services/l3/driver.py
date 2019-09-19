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

import netaddr

from oslo_config import cfg
from oslo_log import log as logging

from networking_kaloom.ml2.drivers.kaloom.common.kaloom_netconf import KaloomNetconf
from networking_kaloom.ml2.drivers.kaloom.common import utils
from networking_kaloom.services.l3 import exceptions as kaloom_exc

LOG = logging.getLogger(__name__)

IPV4_BITS = 32
IPV6_BITS = 128

class KaloomL3Driver(object):
    """Wraps Kaloom vFabric Netconf.

    All communications between Neutron and vFabric are over Netconf.
    """
    def __init__(self, prefix):
        self.vfabric = KaloomNetconf(cfg.CONF.KALOOM.kaloom_host,
                                    cfg.CONF.KALOOM.kaloom_port,
                                    cfg.CONF.KALOOM.kaloom_username,
                                    cfg.CONF.KALOOM.kaloom_private_key_file,
                                    cfg.CONF.KALOOM.kaloom_password)
        self.prefix = prefix

    def get_routers(self):
        """existing routers in Kaloom vFabric, related to OpenStack instance"""
        all_routers =  self.vfabric.list_router_name_id() #raises Exception on error
        openstack_routers = {}
        for (router_name, router_node_id) in all_routers:
            if router_name.startswith(self.prefix):
                openstack_routers[router_name] = router_node_id
        return openstack_routers

    def create_router(self, context, router):
        """Creates a router on Kaloom vFabric.
        """
        if router:
            router_name = utils._kaloom_router_name(self.prefix, router['id'],
                                                   router['name'])

            try:
                LOG.info('Trying to create_router %s in vfabric', router_name)
                self.vfabric.create_router(router_name)
            except Exception as e:
                msg = (_('Failed to create router %s on Kaloom vFabric, err:%s') %
                         (router_name, e))
                LOG.error(msg)
                raise kaloom_exc.KaloomServicePluginRpcError(msg=msg)

    def delete_router(self, context, router_id, router):
        """Deletes a router from Kaloom vFabric."""
        if router:
            router_name = utils._kaloom_router_name(self.prefix, router_id, router['name'])
            LOG.info('Trying to delete_router %s in vfabric', router_name)
            vfabric_router_id = self.vfabric.get_router_id_by_name(router_name)
            if vfabric_router_id is None:
                LOG.warning('No such vfabric router=%s to delete', router_name)
                return

            self.vfabric.delete_router(vfabric_router_id)

    def update_router(self, context, router_id, original_router, new_router):
        """Updates a router which is already created on Kaloom vFabric.
        """
        ori_router_name = utils._kaloom_router_name(self.prefix, router_id, original_router['name'])
        new_router_name = utils._kaloom_router_name(self.prefix, router_id, new_router['name'])
        try:
            LOG.info('Trying to rename vfabric router %s to %s', ori_router_name, new_router_name)
            vfabric_router_id = self.vfabric.get_router_id_by_name(ori_router_name)
            if vfabric_router_id is None:
                msg = "non-existing vfabric router"
                raise ValueError(msg)

            router_info={'router_node_id': vfabric_router_id, 'router_name': new_router_name}
            self.vfabric.rename_router(router_info)
        except Exception as e:
            msg = (_('Failed to rename vFabric router %s to %s, err:%s') % (ori_router_name, new_router_name, e))
            LOG.error(msg)
            raise kaloom_exc.KaloomServicePluginRpcError(msg=msg)

    def update_router_routes_info(self, context, router_id, original_router, new_routes_info):
        """ Updates a router's extra-routes as new_routes_info on Kaloom vFabric.
        """
        if original_router:
            router_name = utils._kaloom_router_name(self.prefix, router_id, original_router['name'])
            try:
                LOG.info('Trying to update routes %s on vfabric router %s', new_routes_info, router_name)
                vfabric_router_id = self.vfabric.get_router_id_by_name(router_name)
                if vfabric_router_id is None:
                    msg = "non-existing vfabric router"
                    raise ValueError(msg)

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
                    self.vfabric.add_ip_static_route(route_info)

                for (destination, nexthop) in delete:
                    route_info = {'router_node_id': vfabric_router_id, 'destination_prefix': destination}
                    route_info['ip_version'] = netaddr.IPNetwork(destination.split('/')[0]).version
                    self.vfabric.delete_ip_static_route(route_info)

            except Exception as e:
                msg = (_('Failed to update routes %s on vfabric router %s, err:%s') % (new_routes_info, router_name, e))
                LOG.error(msg)
                raise kaloom_exc.KaloomServicePluginRpcError(msg=msg)

    def router_l2node_link_exists(self, router_id, name, l2_node_id):
        """ check the link between router and l2_node exists or not. 
        """
        if router_id:
            router_name = utils._kaloom_router_name(self.prefix, router_id, name)
            try:
                router_inf_info = self.vfabric.get_router_interface_info(router_name, l2_node_id)
                vfabric_router_id = router_inf_info['node_id']
                tp_interface_name = router_inf_info['interface']
                if vfabric_router_id is not None and tp_interface_name is not None:
                    return True
                else:
                    return False
            except Exception as e:
                msg = (_('Failed to check router--l2_node %s--%s link existence on Kaloom vFabric, err:%s') %
                       (router_name, l2_node_id, e))
                LOG.error(msg)
                raise kaloom_exc.KaloomServicePluginRpcError(msg=msg)

    def add_router_interface(self, context, router_info):
        """In case of no router interface present for the network of subnet, creates the interface.
        Adds a subnet configuration to the router interface on Kaloom vFabric.
        This deals with both IPv6 and IPv4 configurations. 
        """
        def _get_overlapped_subnet(given_ip_cidr, existing_ip_cidrs ):
            given_net = netaddr.IPNetwork(given_ip_cidr)
            for ip_cidr in existing_ip_cidrs:
                existing_net = netaddr.IPNetwork(ip_cidr)
                if given_net in existing_net or existing_net in given_net:
                    return ip_cidr
            return None

        if router_info:
            router_name = utils._kaloom_router_name(self.prefix, router_info['id'],
                                                   router_info['name'])
            l2_node_id = router_info['nw_name']
            try:
                LOG.info('Trying to add subnet %s to vfabric router %s -- network %s', router_info['subnet_id'], router_name, l2_node_id)
                router_inf_info = self.vfabric.get_router_interface_info(router_name, l2_node_id)
                vfabric_router_id = router_inf_info['node_id']
                tp_interface_name = router_inf_info['interface']
                if vfabric_router_id is None:
                    msg = "non-existing vfabric router"
                    raise ValueError(msg)

                ## first subnet request ? absence of router--l2_node interface, first create interface.
                attach_router_called = False
                if tp_interface_name is None:
                    tp_interface_name = self.vfabric.attach_router(vfabric_router_id, l2_node_id)
                    attach_router_called = True

                #interface_info common to both add and delete.
                interface_info={}
                interface_info['router_node_id'] = vfabric_router_id
                interface_info['interface_name'] = tp_interface_name
                interface_info['ip_version'] = router_info['ip_version']
                prefix_length = router_info['cidr'].split('/')[1]

                #plugin.remove_router_interface left stale data on vfabric? not cleaned yet? then reuse or update.
                #otherwise multiple IPs of same subnet would complain "That ipv4 address already exist for that router"
                given_ip_cidr = '%s/%s' % (router_info['ip_address'], prefix_length)
                overlapped_subnet_ip_cidr = _get_overlapped_subnet(given_ip_cidr, router_inf_info['cidrs'] )
                if overlapped_subnet_ip_cidr is not None:
                    if given_ip_cidr == overlapped_subnet_ip_cidr:
                        #already exists exact ip/subnet in vfabric, nothing to do.
                        return
                    else:
                        #clean overlap now: by calling delete_ipaddress_to_interface
                        interface_info['ip_address'] = overlapped_subnet_ip_cidr.split('/')[0]
                        self.vfabric.delete_ipaddress_from_interface(interface_info)

                #add_ipaddress_to_interface
                interface_info['ip_address'] = router_info['ip_address']
                interface_info['prefix_length'] = prefix_length
                try:
                    self.vfabric.add_ipaddress_to_interface(interface_info)
                except Exception as _e:
                    msg = "add_ipaddress_to_interface failed: %s" % (_e)
                    if attach_router_called:
                        self.vfabric.detach_router(vfabric_router_id, l2_node_id)
                    raise ValueError(msg)
            except Exception as e:
                msg = (_('Failed to add subnet %s (IP %s) to vfabric router '
                    '%s -- network %s, err:%s') % (router_info['subnet_id'], router_info['ip_address'], router_name, l2_node_id, e))
                LOG.error(msg)
                raise kaloom_exc.KaloomServicePluginRpcError(msg=msg)

    def remove_router_interface(self, context, router_info):
        """Removes previously configured subnet interface from router on Kaloom vFabric.
        This deals with both IPv6 and IPv4 configurations. In case of no more subnet configuration remained, 
        removes interface connected to network. 
        """
        if router_info:
            router_name = utils._kaloom_router_name(self.prefix, router_info['id'],
                                                   router_info['name'])
            l2_node_id = router_info['nw_name']
            try:
                LOG.info('Trying to remove subnet %s from vfabric router %s -- network %s', router_info['subnet_id'], router_name, l2_node_id)
                router_inf_info = self.vfabric.get_router_interface_info(router_name, l2_node_id)
                vfabric_router_id = router_inf_info['node_id']
                tp_interface_name = router_inf_info['interface']
                count_ip = len(router_inf_info['cidrs'])

                if vfabric_router_id is None:
                    LOG.warning('no router_interface to remove on non-existing vfabric router=%s', router_name)
                    return
 
                if tp_interface_name is None:
                    LOG.warning('no router_interface to remove on router=%s', router_name)
                    return

                router_inf_ip_addresses = [cidr.split('/')[0] for cidr in router_inf_info['cidrs']]
                #last IP subnet remained, detach router
                if count_ip == 0 or (count_ip == 1 and router_info['ip_address'] == router_inf_ip_addresses[0]):
                    self.vfabric.detach_router(vfabric_router_id, l2_node_id)
                elif router_info['ip_address'] in router_inf_ip_addresses:
                    #delete_ipaddress_from_interface
                    interface_info={}
                    interface_info['router_node_id'] = vfabric_router_id
                    interface_info['interface_name'] = tp_interface_name
                    interface_info['ip_version'] = router_info['ip_version']
                    interface_info['ip_address'] = router_info['ip_address']
                    self.vfabric.delete_ipaddress_from_interface(interface_info)
            except Exception as e:
                msg = (_('Failed to remove subnet %s from vfabric router '
                    '%s -- network %s, msg: %s') % (router_info['subnet_id'], router_name, l2_node_id, e))
                raise kaloom_exc.KaloomServicePluginRpcError(msg=msg)
