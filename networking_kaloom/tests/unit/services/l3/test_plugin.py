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
from string import lower

from neutron.tests import base
from mock import MagicMock, patch, Mock, call, ANY
from oslo_utils import uuidutils
from neutron.db import api as db_api
from networking_kaloom.services.l3 import plugin
from networking_kaloom.services.l3.plugin import LOG
from networking_kaloom.services.l3 import driver as kaloom_l3_driver
from networking_kaloom.ml2.drivers.kaloom.db.kaloom_models import KaloomConcurrency
from networking_kaloom.ml2.drivers.kaloom.common import constants as kconst
from networking_kaloom.ml2.drivers.kaloom.db import kaloom_db

from neutron_lib import context as neutron_context
from neutron_lib.services import base as service_base
from neutron.db import extraroute_db
from neutron.db import l3_gwmode_db
from neutron.db import l3_agentschedulers_db

LOG.info = Mock()
LOG.warning = Mock()

LOG_MESSAGE_READ = 'Fake Syncing Neutron Router DB <-> vFabric'
LOG_MESSAGE_SYNC_INTERFACES_LOCK_WARNING = 'sync_router_interfaces failed to lock router'

class SubstringMatcher():
    def __init__(self, containing):
        self.containing = lower(containing)
    def __eq__(self, other):
        return lower(other).find(self.containing) > -1
    def __unicode__(self):
        return 'a string containing "%s"' % self.containing
    def __str__(self):
        return unicode(self).encode('utf-8')
    __repr__=__unicode__

def get_mock_router_kwargs():
    router_db = Mock(gw_port_id=uuidutils.generate_uuid(),
                            id=uuidutils.generate_uuid())
    router = {'router':
                {'name': 'router1',
                'admin_state_up': True,
                'tenant_id': uuidutils.generate_uuid(),
                'flavor_id': uuidutils.generate_uuid(),
                'id': router_db.id,
                },
                }
    return router

router = get_mock_router_kwargs()

def fake_synchronize_read(self, read_time, routers, vfabric_routers):
    db_session = db_api.get_writer_session()
    with db_session.begin(subtransactions=True):
        kaloom_db.get_Lock(db_session, kconst.L3_LOCK_NAME, read=False, caller_msg = 'l3_sync_read')
        time.sleep(read_time)
        LOG.info(LOG_MESSAGE_READ)

@patch.object(plugin.KaloomL3SyncWorker, 'synchronize', fake_synchronize_read)
def _test_fake_synchronize_read(read_time, routers, vfabric_routers):
    log_calls = [call(LOG_MESSAGE_READ)]
    prefix = '__OpenStack__'
    l3_sync_worker = plugin.KaloomL3SyncWorker(kaloom_l3_driver.KaloomL3Driver(prefix), prefix)
    l3_sync_worker.synchronize(read_time, routers, vfabric_routers)
    LOG.info.assert_has_calls(log_calls)

def _test_sync_router_interfaces(routers, expected):
    prefix = '__OpenStack__'
    l3_sync_worker = plugin.KaloomL3SyncWorker(kaloom_l3_driver.KaloomL3Driver(prefix), prefix)
    l3_sync_worker.sync_router_interfaces(routers)
    LOG.warning.assert_called_with(SubstringMatcher(containing=expected), ANY)

class MockParent(service_base.ServicePluginBase,
                            extraroute_db.ExtraRoute_db_mixin,
                            l3_gwmode_db.L3_NAT_db_mixin,
                            l3_agentschedulers_db.L3AgentSchedulerDbMixin):
    def __init__(self):
        super(MockParent, self).__init__()

    #mock methods
    def create_router(self, context, router):
        return router['router']

    def get_router(self, context, router_id):
        return router['router']

    def delete_router(self, context, router_id):
        pass

    def add_worker(self, MagicMock):
        pass

class KaloomL3ServicePluginTestCase(base.BaseTestCase):
    def setUp(self):
        super(KaloomL3ServicePluginTestCase, self).setUp()
        engine = db_api.get_writer_session().connection().engine
        KaloomConcurrency.__table__.create(bind=engine)
        engine.execute("insert into kaloom_x_s_lock(name) values('" + kconst.L3_LOCK_NAME + "')")
        self.db_context = neutron_context.get_admin_context()

    def tearDown(self):
        super(KaloomL3ServicePluginTestCase, self).tearDown()
        engine = db_api.get_writer_session().connection().engine
        KaloomConcurrency.__table__.drop(bind=engine)

    @patch('networking_kaloom.services.l3.driver.KaloomNetconf',autospec=True)
    def test_router_create_delete_sync_interface(self, mock_KaloomNetconf):
        #patch super class, which has mocked certain methods
        patcher = patch.object(plugin.KaloomL3ServicePlugin, '__bases__', (MockParent,))
        with patcher:
            patcher.is_local = True #avoids delattr error
            l3_plugin = plugin.KaloomL3ServicePlugin()
            mock_KaloomNetconf_instance = mock_KaloomNetconf.return_value

            # creates a router
            method = getattr(l3_plugin, 'create_router')
            method(self.db_context, router)
            mock_KaloomNetconf_instance.create_router.assert_called_once()

            # l3_sync atomic read between neutron_db and vfabric
            # starts a thread that will take the write lock and hold it for a while
            read_time = 4
            routers = [router['router']]
            vfabric_routers = []
            concurrent_test_fake_synchronize_read = threading.Thread(target=_test_fake_synchronize_read, args=(read_time, routers, vfabric_routers))
            concurrent_test_fake_synchronize_read.start()

            # meanwhile try to delete the router
            method = getattr(l3_plugin, 'delete_router')
            method(self.db_context, router['router']['id'])
            mock_KaloomNetconf_instance.delete_router.assert_called_once()

            # once the router is deleted, invokes sync_router_interfaces which should simply 
            # complain that the router does not exist but still return gracefully
            expected = LOG_MESSAGE_SYNC_INTERFACES_LOCK_WARNING
            _test_sync_router_interfaces(routers, expected)

            #wait for threads
            concurrent_test_fake_synchronize_read.join()
