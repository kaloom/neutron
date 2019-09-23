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

import copy

from neutron.common import rpc as n_rpc
from neutron_lib.agent import topics
from neutron_lib import constants as n_const
from neutron_lib import context as nctx
from neutron_lib.plugins import constants as plugin_constants
from neutron_lib.plugins import directory
from neutron_lib.services import base as service_base
from neutron_lib import worker
from neutron_lib import exceptions as n_exc
from oslo_config import cfg
from oslo_log import helpers as log_helpers
from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import excutils
from neutron.api.rpc.agentnotifiers import l3_rpc_agent_api
from neutron.api.rpc.handlers import l3_rpc
from neutron.db import extraroute_db
from neutron.db import l3_agentschedulers_db
from neutron.db import l3_gwmode_db
from neutron.plugins.ml2.driver_context import NetworkContext  # noqa

from networking_kaloom.services.l3 import driver as kaloom_l3_driver
from networking_kaloom.ml2.drivers.kaloom.common import constants as kconst
from networking_kaloom.ml2.drivers.kaloom.common import utils
from neutron_lib.db import api as db_api
from networking_kaloom.ml2.drivers.kaloom.db import kaloom_db
from eventlet import greenthread

LOG = logging.getLogger(__name__)


class KaloomL3SyncWorker(worker.BaseWorker):
    def __init__(self, driver, prefix):
        self.driver = driver
        self.prefix = prefix
        self._loop = None
        super(KaloomL3SyncWorker, self).__init__(worker_process_count=0)

    def start(self):
        super(KaloomL3SyncWorker, self).start()
        interval_val = cfg.CONF.KALOOM.l3_sync_interval
        if interval_val == 0: #synchronize at startup but no refresh
            self.synchronize()
        else:
            if self._loop is None:
               self._loop = loopingcall.FixedIntervalLoopingCall(
                             self.synchronize
                             )
            self._loop.start(interval=interval_val)

    def stop(self):
        if self._loop is not None:
            self._loop.stop()

    def wait(self):
        if self._loop is not None:
            self._loop.wait()
        self._loop = None

    def reset(self):
        self.stop()
        self.wait()
        self.start()

    def get_subnet_info(self, subnet_id):
        return self.get_subnet(subnet_id)

    def get_router_interfaces(self, r):
        core = directory.get_plugin()
        ctx = nctx.get_admin_context()
        grouped_router_interfaces = {}
        ports = core.get_ports(ctx, filters={'device_id': [r['id']]}) or []
        for p in ports:
            for fixed_ip in p['fixed_ips']:
                router_interface = r.copy()
                subnet_id = fixed_ip['subnet_id']
                subnet = core.get_subnet(ctx, subnet_id)
                network_id = p['network_id']
                nw_name = utils._kaloom_nw_name(self.prefix, network_id)
                router_interface['nw_name'] = nw_name
                router_interface['ip_address'] = fixed_ip['ip_address']
                router_interface['cidr'] = subnet['cidr']
                router_interface['gip'] = subnet['gateway_ip']
                router_interface['ip_version'] = subnet['ip_version']
                router_interface['subnet_id'] = subnet_id
                if nw_name in grouped_router_interfaces:
                    grouped_router_interfaces[nw_name].append(router_interface)
                else:
                    grouped_router_interfaces[nw_name] = [router_interface]
        return grouped_router_interfaces

    def synchronize(self):
        """Synchronizes Router DB from Neturon DB with Kaloom Fabric.

        Walks through the Neturon Db and ensures that all the routers
        created in Netuton DB match with Kaloom Fabric. After creating appropriate
        routers, it ensures to add interfaces as well.
        Stranded routers in vFabric get deleted.
        Uses idempotent properties of Kaloom vFabric configuration, which means
        same commands can be repeated.
        """
        # Sync (read from neutron_db and vfabric) can't go in parallel with router operations
        # parallelism of router operations
        # write (x) lock during transaction.
        db_session = db_api.get_writer_session()
        with db_session.begin(subtransactions=True):
            try:
                kaloom_db.get_Lock(db_session, kconst.L3_LOCK_NAME, read=False, caller_msg = 'l3_sync_read')
                routers = directory.get_plugin(plugin_constants.L3).get_routers(nctx.get_admin_context())
                vfabric_routers = self.driver.get_routers()
            except Exception as e:
                LOG.warning(e)
                return
        LOG.info('Syncing Neutron Router DB <-> vFabric')
        self.sync_routers(routers, vfabric_routers)
        self.sync_router_interfaces(routers)

    def sync_routers(self, routers, vfabric_routers):
        try:
           #create routers if does not exist in vfabric
           for r in routers:
               vfabric_router = utils._kaloom_router_name(self.prefix, r['id'], r['name'])
               if vfabric_router in vfabric_routers.keys():
                   #mark as non-stranding router
                   vfabric_routers.pop(vfabric_router, None)
               else:
                   try:
                       self.driver.create_router(self, r)
                   except Exception as e:
                       LOG.error("sync_routers failed to create router=%s, msg:%s", vfabric_router, e)
           # remove stranded vfabric routers
           # possibility of stranded routers: router creation after netconf timeout; manually added routers in vFabric, failed deletion 
           for vfabric_router in vfabric_routers.keys():
               router_node_id = vfabric_routers[vfabric_router]
               try:
                  LOG.info('Trying to delete_router %s in vfabric', vfabric_router)
                  self.driver.vfabric.delete_router(router_node_id)
               except Exception as e:
                  LOG.error("sync_routers failed to delete router=%s, msg:%s", vfabric_router, e)
        except Exception as e:
            LOG.error("sync_routers failed, msg:%s", e)

    def sync_router_interfaces(self, routers):
        for r in routers:
            # Sync (vfabric.add_router_interface) can't go in parallel with router operations (on same router)
            # to avoid race condition of creating router--network link.
            # parallelism of router operations (on different router)
            # read (s) lock on "the router" during transaction.
            db_session = db_api.get_writer_session()
            with db_session.begin(subtransactions=True):
                try:
                    caller_msg = 'l3_sync_interface on router id=%s name=%s' % (r['id'] , r['name'])
                    kaloom_db.get_Lock(db_session, r['id'], read=True, caller_msg = caller_msg)
                except Exception as e:
                    #no record (router deleted): nothing to sync for the router
                    #lock timeout 
                    LOG.warning("sync_router_interfaces failed to lock router, err:%s", e)
                    continue
                grouped_router_interfaces = self.get_router_interfaces(r)
                for nw_name in grouped_router_interfaces.keys():
                    try:
                        if not self.driver.router_l2node_link_exists(r['id'], r['name'], nw_name):
                            router_interfaces = grouped_router_interfaces[nw_name]
                            for ri in router_interfaces:
                                try:
                                    self.driver.add_router_interface(self, ri)
                                except Exception as e:
                                    LOG.error("sync_router_interfaces failed to add_router_interface msg:%s", e)
                    except Exception as e:
                        LOG.error("sync_router_interfaces failed to check link existence:%s--%s, msg:%s", r['name'], nw_name, e)
            
class KaloomL3ServicePlugin(service_base.ServicePluginBase,
                            extraroute_db.ExtraRoute_db_mixin,
                            l3_gwmode_db.L3_NAT_db_mixin,
                            l3_agentschedulers_db.L3AgentSchedulerDbMixin):

    """Implements L3 Router service plugin for Kaloom Fabric.

    Creates routers in Kaloom Fabric, manages them, adds/deletes interfaces
    to the routes.
    """

    supported_extension_aliases = ["router", "ext-gw-mode",
                                   "extraroute"] #"router-interface-fip", "fip64" not supported.

    def __init__(self, driver=None):
        super(KaloomL3ServicePlugin, self).__init__()
        self.prefix = '__OpenStack__'
        self.driver = driver or kaloom_l3_driver.KaloomL3Driver(self.prefix)
        self.setup_rpc()
        self.add_worker(KaloomL3SyncWorker(self.driver, self.prefix))

    def setup_rpc(self):
        # RPC support
        self.topic = topics.L3PLUGIN
        self.conn = n_rpc.Connection()
        self.agent_notifiers.update(
            {n_const.AGENT_TYPE_L3: l3_rpc_agent_api.L3AgentNotifyAPI()})
        self.endpoints = [l3_rpc.L3RpcCallback()]
        self.conn.create_consumer(self.topic, self.endpoints,
                                  fanout=False)
        self.conn.consume_in_threads()

    def _update_port_up(self, context, port_id):
        #Update port STATUS ACTIVE
        core = directory.get_plugin()
        # tempest test complains port_id could not be found.
        # The port_up will be moved to netconf notification callback.
        try:
           core.update_port(context, port_id, {'port': {'status': 'ACTIVE'}})
        except Exception:
           pass

    def get_plugin_type(self):
        return plugin_constants.L3

    def get_plugin_description(self):
        """Returns string description of the plugin."""
        return ("Kaloom L3 Router Service Plugin for Kaloom vFabric "
                "based routing")

    @log_helpers.log_method_call
    def create_router(self, context, router):
        """Create a new router entry in DB, and create it in vFabric."""
        # create_router can't go in parallel with l3_sync (synchronize)
        # parallelism of router operations
        # shared (S) lock during transaction.
        db_session = db_api.get_writer_session()
        with db_session.begin(subtransactions=True):
            caller_msg = 'create_router %s' % router['router']['name']
            kaloom_db.get_Lock(db_session, kconst.L3_LOCK_NAME, read=True, caller_msg = caller_msg)

            # Add router to the DB
            new_router = super(KaloomL3ServicePlugin, self).create_router(
                context,
                router)
            # create router on the vFabric
            try:
                self.driver.create_router(context, new_router)
                #Add router-id to the KaloomConcurrency table (later use for x/s lock)
                kaloom_db.create_entry_for_Lock(new_router['id'])
                return new_router
            except Exception:
                with excutils.save_and_reraise_exception():
                    super(KaloomL3ServicePlugin, self).delete_router(
                        context,
                        new_router['id']
                    )

    def _set_external_gateway(self, context, router_id, network_id,
                             original_router, new_router):
        try:
            nw_name = utils._kaloom_nw_name(self.prefix, network_id)
        except n_exc.NetworkNotFound as e:
            msg = ('can not _set_external_gateway as no such network=%s, msg:%s' % (network_id, e))
            LOG.error(msg)
            return

        core = directory.get_plugin()

        ip_address = new_router['external_gateway_info']['external_fixed_ips'][0]['ip_address']
        subnet_id = new_router['external_gateway_info']['external_fixed_ips'][0]['subnet_id']
        subnet = core.get_subnet(context, subnet_id)

        # Package all the info needed for vFabric programming
        router_info = copy.deepcopy(new_router)
        router_info['nw_name'] = nw_name
        router_info['subnet_id'] = subnet_id
        router_info['ip_address'] = ip_address
        router_info['cidr'] = subnet['cidr']
        router_info['gip'] = subnet['gateway_ip']
        router_info['ip_version'] = subnet['ip_version']

        self.driver.add_router_interface(context, router_info)
        self._update_port_up(context, new_router['gw_port_id'])

    def _unset_external_gateway(self, context, router_id, router_unset_ext_gw):
        # Get ip_address info for the subnet that is being deleted from the router.
        original_router = self.get_router(context, router_id)
        core = directory.get_plugin()

        if original_router['external_gateway_info'] is None or len(original_router['external_gateway_info']['external_fixed_ips']) == 0: ##nothing to unset
            new_router = super(KaloomL3ServicePlugin, self).update_router(context, router_id, router_unset_ext_gw)
            return new_router

        ip_address = original_router['external_gateway_info']['external_fixed_ips'][0]['ip_address']
        subnet_id = original_router['external_gateway_info']['external_fixed_ips'][0]['subnet_id']
        subnet = core.get_subnet(context, subnet_id)

        # Update router DB
        new_router = super(KaloomL3ServicePlugin, self).update_router(context, router_id, router_unset_ext_gw)

        # Get network information of the gateway subnet that is being removed for vFabric programming
        network_id = subnet['network_id']
        try:
            nw_name = utils._kaloom_nw_name(self.prefix, network_id)
        except n_exc.NetworkNotFound as e:
            LOG.warning('can not _unset_external_gateway as no such network=%s, msg:%s', network_id, e)
            return new_router

        router_info = copy.deepcopy(new_router)
        router_info['nw_name'] = nw_name
        router_info['subnet_id'] = subnet_id
        router_info['ip_address'] = ip_address
        router_info['ip_version'] = subnet['ip_version']

        self.driver.remove_router_interface(context, router_info)
        return new_router

    @log_helpers.log_method_call
    def update_router(self, context, router_id, router):
        """Update an existing router in DB, and update it in Kaloom vFabric."""

        # Read existing router record from DB
        original_router = self.get_router(context, router_id)

        try:
            r = router['router']
            #support for extra-routes
            new_routes_info = r['routes'] if r.has_key('routes') else None

            #support for external_gateway_info
            external_gateway_info = r['external_gateway_info'] if r.has_key('external_gateway_info') else None

            #support for router re/name
            new_name = r['name'] if r.has_key('name') else None
            #
            if new_routes_info is not None:
                # Update router DB
                new_router = super(KaloomL3ServicePlugin, self).update_router(context, router_id, router)
                # Modify router on the vFabric
                self.driver.update_router_routes_info(context, router_id, 
                                                     original_router, new_routes_info)

            elif external_gateway_info is not None:
                if external_gateway_info == {}: # "unset --external-gateway" get called
                    # "unset --external-gateway" can't go in parallel with l3_sync_interface on same router
                    # parallelism of router operations (on different router)
                    # write (x) lock on "the router" during transaction.
                    db_session = db_api.get_writer_session()
                    with db_session.begin(subtransactions=True):
                        caller_msg = 'unset_external_gateway on router id=%s name=%s' % (router_id, original_router['name'])
                        kaloom_db.get_Lock(db_session, router_id, read=False, caller_msg = caller_msg)
                        new_router = self._unset_external_gateway(context, router_id, router)
                else: # "set --external-gateway" get called
                    network_id = external_gateway_info['network_id']
                    ##Kaloom does not support SNAT
                    if 'enable_snat' not in external_gateway_info.keys() or external_gateway_info['enable_snat'] == True:
                       raise n_exc.BadRequest(resource='router', msg='SNAT not supported in vFabric')
                    # "set --external-gateway" can't go in parallel with l3_sync_interface on same router
                    # parallelism of router operations (on different router)
                    # write (x) lock on "the router" during transaction.
                    db_session = db_api.get_writer_session()
                    with db_session.begin(subtransactions=True):
                        caller_msg = 'set_external_gateway on router id=%s name=%s' % (router_id, original_router['name'])
                        kaloom_db.get_Lock(db_session, router_id, read=False, caller_msg = caller_msg)
                        # Update router DB
                        new_router = super(KaloomL3ServicePlugin, self).update_router(context, router_id, router)
                        # Modify router on the vFabric
                        if len(new_router['external_gateway_info']['external_fixed_ips']) > 0:
                            self._set_external_gateway(context, router_id, network_id,
                                                       original_router, new_router)
            else:
                # Update router DB
                new_router = super(KaloomL3ServicePlugin, self).update_router(context, router_id, router)
                # Modify router on the vFabric
                if new_name is not None and new_name != original_router['name']:
                   ##rename router in vFabric
                   self.driver.update_router(context, router_id,
                                         original_router, new_router)
            return new_router
        except Exception as e:
            #re-raise exception 
            with excutils.save_and_reraise_exception():
               msg = "update_router failed: %s" % (e)
               LOG.error(msg)
        
    @log_helpers.log_method_call
    def delete_router(self, context, router_id):
        """Delete an existing router from Kaloom vFabric as well as from the DB."""
        router = self.get_router(context, router_id)
        router_name = utils._kaloom_router_name(self.prefix, router_id, router['name'])
        # delete_router can't go in parallel with l3_sync (synchronize)
        # parallelism of router operations
        # shared (S) lock during transaction.
        db_session = db_api.get_writer_session()
        with db_session.begin(subtransactions=True):
            caller_msg = 'delete_router %s' % router_name
            kaloom_db.get_Lock(db_session, kconst.L3_LOCK_NAME, read=True, caller_msg = caller_msg)

            # Delete on neutron database
            super(KaloomL3ServicePlugin, self).delete_router(context, router_id)

            #delete router-id from the KaloomConcurrency table (no more future x/s lock)
            kaloom_db.delete_entry_for_Lock(router_id)

            # Delete router on the Kaloom vFabric, in case former does not raise exception
            try:
                self.driver.delete_router(context, router_id, router)
            except Exception as e:
                msg = "Failed to delete router %s on Kaloom vFabric, err:%s" % (router_name, e)
                LOG.warning(msg)
                # do not throw exception, cleanup process will clean stranded vfabric routers later.

    def _get_subnet_ip_from_router_info(self, router_info, subnet_id, network_id, gip):
        #In case of internal subnet, returns gip as the ip-address of router interface.
        #In case of external subnet, returns ip_address from router_info['external_gateway_info']['external_fixed_ips']

        ext_gw_info = router_info['external_gateway_info']
        if ext_gw_info is not None and ext_gw_info.has_key('network_id') and ext_gw_info.has_key('external_fixed_ips') and ext_gw_info['network_id'] == network_id:
           for external_fixed_ip in ext_gw_info['external_fixed_ips']:
              if external_fixed_ip['subnet_id'] == subnet_id:
                 return external_fixed_ip['ip_address']
           return None
        else:
           return gip

    def _get_subnet_ip(self, fixed_ips, subnet_id):
        for fixed_ip in fixed_ips:
            if fixed_ip['subnet_id'] == subnet_id:
                return fixed_ip['ip_address']

    @log_helpers.log_method_call
    def add_router_interface(self, context, router_id, interface_info):
        """Add a subnet of a network to an existing router."""
        router = self.get_router(context, router_id)
        # add_router_interface can't go in parallel with l3_sync_interface on same router
        # parallelism of router operations (on different router)
        # write (x) lock on "the router" during transaction.
        db_session = db_api.get_writer_session()
        with db_session.begin(subtransactions=True):
            caller_msg = 'add_router_interface on router id=%s name=%s' % (router_id, router['name'])
            kaloom_db.get_Lock(db_session, router_id, read=False, caller_msg = caller_msg)
            new_router_ifc = super(KaloomL3ServicePlugin, self).add_router_interface(
                context, router_id, interface_info)

            core = directory.get_plugin()

            # Get network info for the subnet that is being added to the router.
            # Check if the interface information is by port-id or subnet-id
            add_by_port, add_by_sub = self._validate_interface_info(interface_info)
            if add_by_sub:
                subnet = core.get_subnet(context, interface_info['subnet_id'])
                port = core.get_port(context, new_router_ifc['port_id'])
                #port has multiple (ip_address, subnet_id)
                ip_address = self._get_subnet_ip(port['fixed_ips'], interface_info['subnet_id'])
            elif add_by_port:
                port = core.get_port(context, interface_info['port_id'])
                ip_address = port['fixed_ips'][0]['ip_address']
                subnet_id = port['fixed_ips'][0]['subnet_id']
                subnet = core.get_subnet(context, subnet_id)

            # Package all the info needed for vFabric programming
            network_id = subnet['network_id']
            try:
                nw_name = utils._kaloom_nw_name(self.prefix, network_id)
            except n_exc.NetworkNotFound as e:
                LOG.warning('Nothing to do in add_router_interface as no such network=%s, msg:%s', network_id, e)
                return new_router_ifc

            router_info = copy.deepcopy(new_router_ifc)
            router_info['nw_name'] = nw_name
            router_info['ip_address'] = ip_address
            router_info['name'] = router['name']
            router_info['cidr'] = subnet['cidr']
            router_info['gip'] = subnet['gateway_ip']
            router_info['ip_version'] = subnet['ip_version']

            try:
                self.driver.add_router_interface(context, router_info)
                self._update_port_up(context, port['id'])
                return new_router_ifc
            except Exception:
                with excutils.save_and_reraise_exception():
                    super(KaloomL3ServicePlugin, self).remove_router_interface(
                        context,
                        router_id,
                        interface_info)

    @log_helpers.log_method_call
    def remove_router_interface(self, context, router_id, interface_info):
        """Remove a subnet of a network from an existing router."""
        router = self.get_router(context, router_id)
        # remove_router_interface can't go in parallel with l3_sync_interface on same router
        # parallelism of router operations (on different router)
        # write (x) lock on "the router" during transaction.
        db_session = db_api.get_writer_session()
        with db_session.begin(subtransactions=True):
            caller_msg = 'remove_router_interface on router id=%s name=%s' % (router_id, router['name'])
            kaloom_db.get_Lock(db_session, router_id, read=False, caller_msg = caller_msg)
            # Get ip_address info for the subnet that is being deleted from the router.
            # Check if the interface information is by port-id or subnet-id
            core = directory.get_plugin()
            add_by_port, add_by_sub = self._validate_interface_info(interface_info)
            if add_by_sub:
                subnet = core.get_subnet(context, interface_info['subnet_id'])
                ip_address = self._get_subnet_ip_from_router_info(router, interface_info['subnet_id'], subnet['network_id'], subnet['gateway_ip'])
            elif add_by_port:
                port = core.get_port(context, interface_info['port_id'])
                ip_address = port['fixed_ips'][0]['ip_address']
                subnet_id = port['fixed_ips'][0]['subnet_id']
                subnet = core.get_subnet(context, subnet_id)

            router_ifc_to_del = (
                super(KaloomL3ServicePlugin, self).remove_router_interface(
                    context,
                    router_id,
                    interface_info)
                )

            # Get network information of the subnet that is being removed
            network_id = subnet['network_id']
            try:
                nw_name = utils._kaloom_nw_name(self.prefix, network_id)
            except n_exc.NetworkNotFound as e:
                LOG.warning('Nothing to do in remove_router_interface as no such network=%s, msg:%s', network_id, e)
                return

            router_info = copy.deepcopy(router_ifc_to_del)
            router_info['nw_name'] = nw_name
            router_info['name'] = router['name']
            router_info['ip_address'] = ip_address
            router_info['ip_version'] = subnet['ip_version']

            try:
                self.driver.remove_router_interface(context, router_info)
                return router_ifc_to_del
            except Exception as e:
                msg = "remove_router_interface failed in vfabric: %s" % (e)
                LOG.error(msg)