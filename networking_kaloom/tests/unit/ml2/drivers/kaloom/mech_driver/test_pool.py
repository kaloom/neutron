# Copyright 2019 Kaloom, Inc.  All rights reserved.
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

from neutron.tests import base
from neutron.db import api as db_api

from networking_kaloom.ml2.drivers.kaloom.mech_driver.pool import KaloomVlanPool
from networking_kaloom.ml2.drivers.kaloom.db.kaloom_models import KaloomVlanHostMapping, KaloomKnidMapping, KaloomVlanReservation
from networking_kaloom.ml2.drivers.kaloom.db import kaloom_db

from mock import MagicMock, patch


class TestKaloomVlanPool(base.BaseTestCase):
    def setUp(self):
        super(TestKaloomVlanPool, self).setUp()
        session = db_api.get_writer_session()
        conn = session.connection()
        engine = conn.engine
        KaloomKnidMapping.__table__.create(bind=engine)
        KaloomVlanHostMapping.__table__.create(bind=engine)
        KaloomVlanReservation.__table__.create(bind=engine)
        with patch.object(KaloomVlanPool, '_parse_network_vlan_ranges', return_value=(2,4094)):
             self.pool = KaloomVlanPool()

    def tearDown(self):
        super(TestKaloomVlanPool, self).tearDown()
        conn = db_api.get_writer_session().connection()
        engine = conn.engine
        KaloomKnidMapping.__table__.drop(bind=engine)
        KaloomVlanHostMapping.__table__.drop(bind=engine)
        KaloomVlanReservation.__table__.drop(bind=engine)

    def test_allocate_local_vlan(self):
        kaloom_db.create_vlan_reservation = MagicMock()
        host_1 = 'fake_host_1'
        network_1 = 'fake_network_1'
        kaloom_db.get_all_vlan_mappings_for_host = MagicMock(return_value=[])
        local_vlan_id = self.pool.allocate_local_vlan(host_1, network_1)
        self.assertEquals(2, local_vlan_id,
                          "Allocation should start with ID=2")

        mapping1 = KaloomVlanHostMapping()
        mapping1.network_id = 'fake_network_id'
        mapping1.host = host_1
        mapping1.vlan_id = local_vlan_id
        kaloom_db.get_all_vlan_mappings_for_host = MagicMock(return_value=[mapping1])

        local_vlan_id = self.pool.allocate_local_vlan(host_1, network_1)
        self.assertEquals(3, local_vlan_id,
                          "Allocation should be increased to ID=3")

        host_2 = 'fake_host_2'
        network_2 = 'fake_network_2'
        kaloom_db.get_all_vlan_mappings_for_host = MagicMock(return_value=[])
        local_vlan_id = self.pool.allocate_local_vlan(host_2, network_2)
        self.assertEquals(2, local_vlan_id,
                          "Allocation should start with ID=2")


