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

from mock import patch, Mock
from oslo_utils import uuidutils
from neutron.tests import base
from neutron_lib import context as neutron_context
from networking_kaloom.ml2.drivers.kaloom.common import utils
from networking_kaloom.services.l3 import driver as kaloom_l3_driver
from networking_kaloom.services.l3.driver import LOG

LOG.error = Mock()

class KaloomL3DriverTestCase(base.BaseTestCase):
    PREFIX = '__OpenStack__'
    DB_CONTEXT = neutron_context.get_admin_context()
    ROUTER_INFO = {'id': uuidutils.generate_uuid(), 
                'name': 'router1',
                'nw_name': utils._kaloom_nw_name(PREFIX, uuidutils.generate_uuid()),
                'subnet_id': uuidutils.generate_uuid(),
                'ip_address': '192.168.1.15',
                'cidr':'192.168.1.15/24',
                'ip_version':'4',
                'gip': '192.168.1.1'}
    ROUTER_NODE_ID = uuidutils.generate_uuid()
    ROUTER_INTERFACE_INFO_FIRST_TIME = {'node_id': ROUTER_NODE_ID, 'interface': None, 'cidrs': []}
    ROUTER_INTERFACE_INFO_EXACT_STALE = {'node_id': ROUTER_NODE_ID, 'interface': 'net1', 'cidrs': ['192.168.1.15/24']}
    ROUTER_INTERFACE_INFO_NON_EXACT_OVERLAPPING = {'node_id': ROUTER_NODE_ID, 'interface': 'net1', 'cidrs': ['192.168.1.16/24']}

    @patch('networking_kaloom.services.l3.driver.KaloomNetconf',autospec=True)
    def setUp(self, mock_KaloomNetconf):
        super(KaloomL3DriverTestCase, self).setUp()
        self.driver = kaloom_l3_driver.KaloomL3Driver(self.PREFIX)
        self.mock_KaloomNetconf_instance = mock_KaloomNetconf.return_value

    def tearDown(self):
        super(KaloomL3DriverTestCase, self).tearDown()
        self.mock_KaloomNetconf_instance.reset_mock()
        LOG.error.reset_mock()
    
    def test_add_router_interface_first_time(self):
        self.mock_KaloomNetconf_instance.get_router_interface_info = Mock(return_value = self.ROUTER_INTERFACE_INFO_FIRST_TIME)
        self.driver.add_router_interface(self.DB_CONTEXT, self.ROUTER_INFO)

        self.mock_KaloomNetconf_instance.attach_router.assert_called_once()
        self.mock_KaloomNetconf_instance.delete_ipaddress_from_interface.assert_not_called()
        self.mock_KaloomNetconf_instance.add_ipaddress_to_interface.assert_called_once()
        LOG.error.assert_not_called
 
    def test_add_router_interface_exact_stale(self):
        self.mock_KaloomNetconf_instance.get_router_interface_info = Mock(return_value = self.ROUTER_INTERFACE_INFO_EXACT_STALE)
        self.driver.add_router_interface(self.DB_CONTEXT, self.ROUTER_INFO)

        self.mock_KaloomNetconf_instance.attach_router.assert_not_called()
        self.mock_KaloomNetconf_instance.delete_ipaddress_from_interface.assert_not_called()
        self.mock_KaloomNetconf_instance.add_ipaddress_to_interface.assert_not_called()
        LOG.error.assert_not_called

    def test_add_router_interface_non_exact_overlapping(self):
        self.mock_KaloomNetconf_instance.get_router_interface_info = Mock(return_value = self.ROUTER_INTERFACE_INFO_NON_EXACT_OVERLAPPING)
        self.driver.add_router_interface(self.DB_CONTEXT, self.ROUTER_INFO)

        self.mock_KaloomNetconf_instance.attach_router.assert_not_called()
        self.mock_KaloomNetconf_instance.delete_ipaddress_from_interface.assert_called_once()
        self.mock_KaloomNetconf_instance.add_ipaddress_to_interface.assert_called_once()
        LOG.error.assert_not_called

    def test_add_router_interface_undo_attach_router(self):
        self.mock_KaloomNetconf_instance.get_router_interface_info = Mock(return_value = self.ROUTER_INTERFACE_INFO_FIRST_TIME)
        self.mock_KaloomNetconf_instance.add_ipaddress_to_interface = Mock(side_effect = Exception('Boom!'))
        try:
           self.driver.add_router_interface(self.DB_CONTEXT, self.ROUTER_INFO)
        except:
           pass
        self.mock_KaloomNetconf_instance.attach_router.assert_called_once()
        self.mock_KaloomNetconf_instance.detach_router.assert_called_once()