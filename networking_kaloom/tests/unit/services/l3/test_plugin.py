# Copyright 2019 Kaloom, Inc.  All rights reserved.
# Copyright (c) 2018 OpenStack Foundation
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
import threading

from neutron.tests import base
from mock import MagicMock, patch, Mock, call, ANY
from neutron.db import api as db_api
from neutron.db import db_base_plugin_common
from neutron.db import db_base_plugin_v2
from neutron.tests.unit.db import test_db_base_plugin_v2
from oslo_config import cfg as oslo_cfg
from neutron.db.migration import cli as migration_cli
from alembic import config as alembic_config
from sqlalchemy import create_engine
import testing.mysqld

from neutron_lib.plugins import directory
from oslo_utils import importutils
from neutron import manager

from networking_kaloom.services.l3 import plugin
from networking_kaloom.services.l3.plugin import LOG
from networking_kaloom.services.l3 import driver as kaloom_l3_driver
from networking_kaloom.ml2.drivers.kaloom.common import constants as kconst
from networking_kaloom.ml2.drivers.kaloom.db import kaloom_db

from neutron_lib import context as neutron_context
from networking_kaloom.ml2.drivers.kaloom.mech_driver import mech_kaloom
import networking_kaloom.tests.unit.services.l3.helper as test_helper

LOG.info = Mock()
LOG.warning = Mock()
mech_kaloom.KaloomL2CleanupWorker = Mock()

LOG_MESSAGE_SYNC_INTERFACES_LOCK_WARNING = 'sync_router_interfaces failed to lock router'

def _test_fake_synchronize_read(read_time, routers, vfabric_routers):
    LOG_MESSAGE_READ = 'Fake Syncing Neutron Router DB <-> vFabric'
    def fake_synchronize_read(self, read_time, routers, vfabric_routers):
        db_session = db_api.get_writer_session()
        with db_session.begin(subtransactions=True):
            kaloom_db.get_Lock(db_session, kconst.L3_LOCK_NAME, read=False, caller_msg = 'l3_sync_read')
            time.sleep(read_time)
            LOG.info(LOG_MESSAGE_READ)

    plugin.KaloomL3SyncWorker.synchronize = fake_synchronize_read
    prefix = '__OpenStack__'
    l3_sync_worker = plugin.KaloomL3SyncWorker(kaloom_l3_driver.KaloomL3Driver(prefix), prefix)
    l3_sync_worker.synchronize(read_time, routers, vfabric_routers)
    LOG.info.assert_called_with(LOG_MESSAGE_READ)

def _test_sync_router_interfaces(routers, arg='delay_start', argvalue=0):
    def delayed_get_router_interfaces(*args, **kwargs):
        import time
        time.sleep(4)
        r = args[0]
        return original_get_router_interfaces(r)

    prefix = '__OpenStack__'
    l3_sync_worker = plugin.KaloomL3SyncWorker(kaloom_l3_driver.KaloomL3Driver(prefix), prefix)

    if arg == 'delay_start':
       time.sleep(argvalue)
       l3_sync_worker.sync_router_interfaces(routers)
    elif arg == 'hold':
        original_get_router_interfaces = l3_sync_worker.get_router_interfaces
        #add delay inside transaction block of sync_router_interfaces
        l3_sync_worker.get_router_interfaces = Mock(side_effect = delayed_get_router_interfaces)
        l3_sync_worker.sync_router_interfaces(routers)
    elif arg == 'loop_time':
        start_time = time.time()
        while True:
            l3_sync_worker.sync_router_interfaces(routers)
            lapse = time.time() - start_time
            if lapse >= argvalue:
                break

def _call_add_router_interface(l3_plugin, ctx, router_id, interface_info, with_hold = False):
    #db_base_plugin_v2.NeutronDbPluginV2's method without wrapper "@db_api.context_manager.reader", to avoid sqlite
    def get_port(self, context, id, fields=None):
        port = self._get_port(context, id)
        return self._make_port_dict(port, fields)

    def delayed__validate_interface_info(*args, **kwargs):
        import time
        time.sleep(6)
        interface_info = args[0]
        return original__validate_interface_info(interface_info)

    method = getattr(l3_plugin, 'add_router_interface')
    with patch.object(db_base_plugin_common.DbBasePluginCommon, '_store_ip_allocation' , test_helper._store_ip_allocation):
        with patch.object(db_base_plugin_v2.NeutronDbPluginV2, 'get_port' , get_port):
            if with_hold:
                #add delay inside transaction block of add_router_interface
                original__validate_interface_info = l3_plugin._validate_interface_info
                l3_plugin._validate_interface_info = Mock(side_effect = delayed__validate_interface_info)
            # call l3_plugin.add_router_interface
            method(ctx, router_id, interface_info)
            #revert back delay
            if with_hold:
                l3_plugin._validate_interface_info = original__validate_interface_info

def _call_update_router(l3_plugin, ctx, router_id, router, with_hold = False):
    #db_base_plugin_v2.db_base_plugin_common.DbBasePluginCommon's method without wrapper "@db_api.context_manager.reader", to avoid sqlite
    def _get_subnets_by_network(self, context, network_id):
        from neutron.objects import subnet as subnet_obj
        return subnet_obj.Subnet.get_objects(context, network_id=network_id)

    def _kaloom_nw_name(prefix, network_id):
        return prefix + network_id

    def delayed__kaloom_nw_name(prefix, network_id):
        import time
        time.sleep(6)
        return prefix + network_id

    if with_hold:
        patch_as = delayed__kaloom_nw_name
    else:
        patch_as = _kaloom_nw_name

    db_base_plugin_v2.db_base_plugin_common.DbBasePluginCommon._get_subnets_by_network = _get_subnets_by_network
    db_base_plugin_v2.db_base_plugin_common.DbBasePluginCommon._store_ip_allocation = test_helper._store_ip_allocation
    with patch.object(plugin.utils, '_kaloom_nw_name' , patch_as):
        method = getattr(l3_plugin, 'update_router')
        method(ctx, router_id, router)

def _call_remove_router_interface(l3_plugin, ctx, router_id, interface_info, with_hold = False):
    def delayed__validate_interface_info(*args, **kwargs):
        import time
        time.sleep(6)
        interface_info = args[0]
        return original__validate_interface_info(interface_info)

    method = getattr(l3_plugin, 'remove_router_interface')
    if with_hold:
        #add delay inside transaction block of delete_router_interface
        original__validate_interface_info = l3_plugin._validate_interface_info
        l3_plugin._validate_interface_info = Mock(side_effect = delayed__validate_interface_info)
    #call l3_plugin.remove_router_interface
    method(ctx, router_id, interface_info)
    #revert back delay
    if with_hold:
        l3_plugin._validate_interface_info = original__validate_interface_info

class KaloomL3ServicePluginTestCase(base.BaseTestCase):
    def setUp(self):
        super(KaloomL3ServicePluginTestCase, self).setUp()
        self.mysqld = testing.mysqld.Mysqld(my_cnf={'skip-networking': None})
        URL = create_engine(self.mysqld.url()).url

        oslo_cfg.CONF.set_override('connection', URL, group='database')

        #"neutron-db-manage upgrade head" equivalent
        alembic_cfg = migration_cli.get_neutron_config()
        alembic_cfg.neutron_config = oslo_cfg.CONF
        test_helper.upgrade(alembic_cfg)

        #"neutron-kaloom-db-manage upgrade head" equivalent
        script_location = 'networking_kaloom.ml2.drivers.kaloom.db.migration:alembic_migrations'
        alembic_cfg_kaloom = alembic_config.Config()
        alembic_cfg_kaloom.set_main_option("script_location", script_location)
        alembic_cfg_kaloom.neutron_config = oslo_cfg.CONF
        test_helper.upgrade(alembic_cfg_kaloom)

        with patch.object(neutron_context.db_api,'_CTX_MANAGER', test_helper.get_context_manager(URL)):
           self.ctx = neutron_context.get_admin_context()
           self.ctx.session
        #print self.ctx.session.connection().engine

        self.setup_coreplugin(load_plugins=False)
        oslo_cfg.CONF.set_override("core_plugin", test_db_base_plugin_v2.DB_PLUGIN_KLASS)
        oslo_cfg.CONF.set_override("service_plugins", ['segments'])
        manager.init()
        self.l2_plugin = directory.get_plugin()
        self.segments_plugin = importutils.import_object('neutron.services.segments.plugin.Plugin')

        #patch
        plugin.db_api._CTX_MANAGER = test_helper.get_context_manager(URL)
        plugin.kaloom_db.db_api.context_manager = test_helper.get_context_manager(URL)
        db_api.context_manager = test_helper.get_context_manager(URL)

        #fix l3_port_check issue
        def delete_port(context, id, l3_port_check=True):
            return original_delete_port(context, id)

        original_delete_port = self.l2_plugin.delete_port
        self.l2_plugin.delete_port = Mock(side_effect = delete_port)

    def tearDown(self):
        super(KaloomL3ServicePluginTestCase, self).tearDown()
        self.mysqld.stop()

    def create_network_subnet_router(self, l3_plugin, mock_KaloomL3Driver_instance, ext_net = False):
        #create network, subnet in db
        if ext_net:
            net_id = test_helper._create_network_ext(self)
        else:
            net_id = test_helper._create_network(self)
        seg_id = test_helper._create_segment(self, net_id)
        subnet_id = test_helper._create_subnet(self, seg_id, net_id)

        router = test_helper.get_mock_router_kwargs()
        # creates a router
        method = getattr(l3_plugin, 'create_router')
        method(self.ctx, router)
        mock_KaloomL3Driver_instance.create_router.assert_called_once()
        mock_KaloomL3Driver_instance.reset_mock()
        return net_id, subnet_id, router

    @patch('networking_kaloom.services.l3.driver.KaloomNetconf',autospec=True)
    def test_router_create_delete_sync_interface(self, mock_KaloomNetconf):
        #patch super class, which has mocked certain methods
        patcher = patch.object(plugin.KaloomL3ServicePlugin, '__bases__', (test_helper.MockParent,))
        with patcher:
            patcher.is_local = True #avoids delattr error
            l3_plugin = plugin.KaloomL3ServicePlugin()
            mock_KaloomNetconf_instance = mock_KaloomNetconf.return_value

            router = test_helper.get_mock_router_kwargs()
            # creates a router
            method = getattr(l3_plugin, 'create_router')
            method(self.ctx, router)
            mock_KaloomNetconf_instance.create_router.assert_called_once()

            # l3_sync atomic read between neutron_db and vfabric
            # starts a thread that will take the write lock and hold it for a while
            read_time = 4
            routers = [router['router']]
            vfabric_routers = []
            concurrent_test_fake_synchronize_read = threading.Thread(target=_test_fake_synchronize_read,
                                                                    args=(read_time, routers, vfabric_routers))
            concurrent_test_fake_synchronize_read.start()

            # meanwhile try to delete the router
            method = getattr(l3_plugin, 'delete_router')
            method(self.ctx, router['router']['id'])
            mock_KaloomNetconf_instance.delete_router.assert_called_once()

            # once the router is deleted, invokes sync_router_interfaces which should simply 
            # complain that the router does not exist but still return gracefully
            _test_sync_router_interfaces(routers)
            LOG.warning.assert_called_with(test_helper.SubstringMatcher(containing=LOG_MESSAGE_SYNC_INTERFACES_LOCK_WARNING), ANY)

            #wait for threads
            concurrent_test_fake_synchronize_read.join()

    @patch('networking_kaloom.services.l3.plugin.kaloom_l3_driver.KaloomL3Driver',autospec=True)
    def test_concurrent_add_interfaces(self, mock_KaloomL3Driver):
        #patch super class, which has mocked certain methods
        patcher = patch.object(plugin.KaloomL3ServicePlugin, '__bases__', (test_helper.MockParent,))
        with patcher:
            patcher.is_local = True #avoids delattr error
            l3_plugin = plugin.KaloomL3ServicePlugin()
            mock_KaloomL3Driver_instance = mock_KaloomL3Driver.return_value
            net_id, subnet_id, router = self.create_network_subnet_router(l3_plugin, mock_KaloomL3Driver_instance)

            #concurrent "sync router interfaces": loops until loop_time seconds to make sure "sync router interfaces"
            # runs before, in-between and after "add_router_interface"
            loop_time = 4
            routers = [router['router']]
            concurrent_sync_router_interfaces = threading.Thread(target=_test_sync_router_interfaces, args=(routers, 'loop_time', loop_time))
            concurrent_sync_router_interfaces.start()

            #concurrent "add_router_interface"
            time.sleep(2)
            interface_info = {'subnet_id': subnet_id}
            _call_add_router_interface(l3_plugin, self.ctx, router['router']['id'], interface_info, with_hold = False)

            #wait for thread
            concurrent_sync_router_interfaces.join()
            # atomicity rule: Once L3Driver.add_router_interface get called (by plugin.add_router_interface), then only
            # L3Driver.router_l2node_link_exists should be called (by plugin.sync_router_interfaces).
            assert mock_KaloomL3Driver_instance.method_calls[0] == call.add_router_interface(ANY, ANY)

    @patch('networking_kaloom.services.l3.plugin.kaloom_l3_driver.KaloomL3Driver',autospec=True)
    def test_atomicity_of_add_router_interface(self, mock_KaloomL3Driver):
        #patch super class, which has mocked certain methods
        patcher = patch.object(plugin.KaloomL3ServicePlugin, '__bases__', (test_helper.MockParent,))
        with patcher:
            patcher.is_local = True #avoids delattr error
            l3_plugin = plugin.KaloomL3ServicePlugin()
            mock_KaloomL3Driver_instance = mock_KaloomL3Driver.return_value
            net_id, subnet_id, router = self.create_network_subnet_router(l3_plugin, mock_KaloomL3Driver_instance)

            #concurrent "sync router interfaces", runs when below "add_router_interface" is in critical section.
            routers = [router['router']]
            delay_start = 3
            concurrent_sync_router_interfaces = threading.Thread(target=_test_sync_router_interfaces, args=(routers,'delay_start', delay_start))
            concurrent_sync_router_interfaces.start()

            #concurrent "add_router_interface": that holds for certain time
            interface_info = {'subnet_id': subnet_id}
            _call_add_router_interface(l3_plugin, self.ctx, router['router']['id'], interface_info, with_hold = True)

            #wait for thread
            concurrent_sync_router_interfaces.join()
            #sync_router_interfaces should not see router interfaces (before add_router_interface completes)
            # atomicity rule: Once L3Driver.add_router_interface get called (by plugin.add_router_interface), then only
            # L3Driver.router_l2node_link_exists should be called (by plugin.sync_router_interfaces).
            assert mock_KaloomL3Driver_instance.method_calls[0] == call.add_router_interface(ANY, ANY)
            assert mock_KaloomL3Driver_instance.method_calls[1] == call.router_l2node_link_exists(ANY, ANY, ANY)

    @patch('networking_kaloom.services.l3.plugin.kaloom_l3_driver.KaloomL3Driver',autospec=True)
    def test_atomicity_of_sync_router_interfaces(self, mock_KaloomL3Driver):
        #patch super class, which has mocked certain methods
        patcher = patch.object(plugin.KaloomL3ServicePlugin, '__bases__', (test_helper.MockParent,))
        with patcher:
            patcher.is_local = True #avoids delattr error
            l3_plugin = plugin.KaloomL3ServicePlugin()
            mock_KaloomL3Driver_instance = mock_KaloomL3Driver.return_value
            net_id, subnet_id, router = self.create_network_subnet_router(l3_plugin, mock_KaloomL3Driver_instance)

            #concurrent "sync router interfaces", that holds for certain time
            routers = [router['router']]
            concurrent_sync_router_interfaces = threading.Thread(target=_test_sync_router_interfaces, args=(routers,'hold', ))
            concurrent_sync_router_interfaces.start()

            #concurrent "add_router_interface": runs when above "sync router interfaces" is in critical section.
            interface_info = {'subnet_id': subnet_id}
            _call_add_router_interface(l3_plugin, self.ctx, router['router']['id'], interface_info, with_hold = False)

            #wait for thread
            concurrent_sync_router_interfaces.join()
            #sync_router_interfaces should not see router interfaces (that came once it called)
            mock_KaloomL3Driver_instance.router_l2node_link_exists.assert_not_called()

    @patch('networking_kaloom.services.l3.plugin.kaloom_l3_driver.KaloomL3Driver',autospec=True)
    def test_atomicity_of_remove_router_interface(self, mock_KaloomL3Driver):
        #patch super class, which has mocked certain methods
        patcher = patch.object(plugin.KaloomL3ServicePlugin, '__bases__', (test_helper.MockParent,))
        with patcher:
            patcher.is_local = True #avoids delattr error
            l3_plugin = plugin.KaloomL3ServicePlugin()
            mock_KaloomL3Driver_instance = mock_KaloomL3Driver.return_value
            net_id, subnet_id, router = self.create_network_subnet_router(l3_plugin, mock_KaloomL3Driver_instance)

            #add router_interface
            interface_info = {'subnet_id': subnet_id}
            _call_add_router_interface(l3_plugin, self.ctx, router['router']['id'], interface_info, with_hold = False)
            mock_KaloomL3Driver_instance.reset_mock()

            #concurrent "remove_router_interface", that holds for certain time
            with_hold = True
            concurrent_remove_router_interface = threading.Thread(target=_call_remove_router_interface,
                                          args=(l3_plugin, self.ctx, router['router']['id'], interface_info, with_hold))
            concurrent_remove_router_interface.start()

            #add router_interface, runs when above "delete_router_interface" is in critical section.
            time.sleep(2)
            l3_plugin_1 = plugin.KaloomL3ServicePlugin()
            _call_add_router_interface(l3_plugin_1, self.ctx, router['router']['id'], interface_info, with_hold = False)

            #wait for thread
            concurrent_remove_router_interface.join()
            # atomicity rule: while remove_router_interface is running, add_router_interface should get blocked until
            # remove_router_interface completes.
            assert mock_KaloomL3Driver_instance.method_calls[0] == call.remove_router_interface(ANY, ANY)
            assert mock_KaloomL3Driver_instance.method_calls[1] == call.add_router_interface(ANY, ANY)

    @patch('networking_kaloom.services.l3.plugin.kaloom_l3_driver.KaloomL3Driver',autospec=True)
    def test_atomicity_of_unset_external_gateway(self, mock_KaloomL3Driver):
        #patch super class, which has mocked certain methods
        patcher = patch.object(plugin.KaloomL3ServicePlugin, '__bases__', (test_helper.MockParent,))
        with patcher:
            patcher.is_local = True #avoids delattr error
            l3_plugin = plugin.KaloomL3ServicePlugin()
            mock_KaloomL3Driver_instance = mock_KaloomL3Driver.return_value
            net_id, subnet_id, router = self.create_network_subnet_router(l3_plugin, mock_KaloomL3Driver_instance, ext_net = True)

            #set --external-gateway
            router_set_ext = {'router':{'external_gateway_info': {'network_id': net_id, 'enable_snat': False, 
                             'external_fixed_ips': [{'ip_address':'192.168.10.3'}]}}}
            _call_update_router(l3_plugin, self.ctx, router['router']['id'], router_set_ext, with_hold = False)
            mock_KaloomL3Driver_instance.reset_mock()

            #concurrent "unset --external-gateway", that holds for certain time
            with_hold = True
            router_unset_ext = {'router':{'external_gateway_info': {}}}
            concurrent_unset_external_gateway = threading.Thread(target=_call_update_router,
                                          args=(l3_plugin, self.ctx, router['router']['id'], router_unset_ext, with_hold))
            concurrent_unset_external_gateway.start()

            #set --external-gateway, runs when above "unset --external-gateway" is in critical section.
            time.sleep(2)
            l3_plugin_1 = plugin.KaloomL3ServicePlugin()
            _call_update_router(l3_plugin_1, self.ctx, router['router']['id'], router_set_ext, with_hold = False)

            #wait for thread
            concurrent_unset_external_gateway.join()
            # atomicity rule: while unset_external_gateway is running, set_external_gateway should get blocked until
            # unset_external_gateway completes.
            assert mock_KaloomL3Driver_instance.method_calls[0] == call.remove_router_interface(ANY, ANY)
            assert mock_KaloomL3Driver_instance.method_calls[1] == call.add_router_interface(ANY, ANY)
