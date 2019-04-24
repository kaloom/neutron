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


from neutron_lib import context as neutron_context
from neutron.tests import base
import mock
from oslo_config import fixture as config_fixture
from oslo_utils import uuidutils

from networking_kaloom.services.l3 import flavor as l3_flavor

class KaloomL3ServiceProviderTestCase(base.BaseTestCase):
    def setUp(self):
        self.cfg = self.useFixture(config_fixture.Config())
        self.cfg.config(service_plugins=['router'])
        self.db_context = neutron_context.get_admin_context()
        super(KaloomL3ServiceProviderTestCase, self).setUp()
        with mock.patch('networking_kaloom.services.l3.driver.KaloomNetconf',autospec=True) as self.mock_KaloomNetconf:
           self.flavor_driver = l3_flavor.KaloomL3ServiceProvider(mock.MagicMock())

    def _get_mock_router_kwargs(self, operation):
        router_db = mock.Mock(gw_port_id=uuidutils.generate_uuid(),
                              id=uuidutils.generate_uuid())
        if operation == 'create':
           key = 'router'
        elif operation == 'delete':
           key = 'original'

        router = {key:
                  {'name': 'router1',
                   'admin_state_up': True,
                   'tenant_id': uuidutils.generate_uuid(),
                   'flavor_id': uuidutils.generate_uuid(),
                   'id': router_db.id,
                   'external_gateway_info': {'network_id':
                                             uuidutils.generate_uuid()}},
                  'context': self.db_context,
                  "router_db": router_db}

        return router

    def test_router_create_postcommit(self):
        router = self._get_mock_router_kwargs('create')
        router['router_id'] = router['router']['id']
        
        mock_KaloomNetconf_instance = self.mock_KaloomNetconf.return_value
        with mock.patch.object(self.flavor_driver,
                               '_validate_l3_flavor',
                               return_value=True):
            method = getattr(self.flavor_driver, '_router_create_postcommit')
            method('router', mock.ANY, mock.ANY, **router)
            mock_KaloomNetconf_instance.create_router.assert_called_once()

    def test_router_delete_postcommit(self):
        router = self._get_mock_router_kwargs('delete')
        router['router_id'] = router['original']['id']

        mock_KaloomNetconf_instance = self.mock_KaloomNetconf.return_value
        vfabric_router_id = uuidutils.generate_uuid()
        mock_KaloomNetconf_instance.get_router_id_by_name.return_value = vfabric_router_id

        with mock.patch.object(self.flavor_driver,
                               '_validate_l3_flavor',
                               return_value=True):
            method = getattr(self.flavor_driver, '_router_delete_postcommit')
            method('router', mock.ANY, mock.ANY, **router)
            mock_KaloomNetconf_instance.get_router_id_by_name.assert_called_once()
            mock_KaloomNetconf_instance.delete_router.assert_called_once_with(vfabric_router_id)
