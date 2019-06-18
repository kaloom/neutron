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
from mock import patch, call

from neutron_lib import constants as nconst
from neutron_lib.plugins.ml2 import api

from networking_kaloom.ml2.drivers.kaloom.mech_driver.mech_kaloom import KaloomOVSMechanismDriver,KaloomKVSMechanismDriver, LOG
from networking_kaloom.ml2.drivers.kaloom.mech_driver.pool import KaloomVlanPool
from networking_kaloom.ml2.drivers.kaloom.common.kaloom_netconf import KaloomNetconf
from networking_kaloom.ml2.drivers.kaloom.db.kaloom_models import KaloomVlanHostMapping, KaloomKnidMapping
from networking_kaloom.ml2.drivers.kaloom.common import constants as kconst

from neutron.tests.unit.plugins.ml2 import _test_mech_agent as base


def fake_get_vfabric_version(obj):
    return "2018-09-24"


class KaloomMechanismDriverTestCase(base.AgentMechanismBaseTestCase):
    GOOD_MAPPINGS = {'fake_physical_network': 'fake_vswitch'}
    GOOD_CONFIGS = {'vswitch_mappings': GOOD_MAPPINGS}

    BAD_MAPPINGS = {'wrong_physical_network': 'wrong_vswitch'}
    BAD_CONFIGS = {'vswitch_mappings': BAD_MAPPINGS}

    AGENT_OVS = {'alive': True,
                 'configurations': GOOD_CONFIGS,
                 'host': 'host',
                 'agent_type': nconst.AGENT_TYPE_OVS}

    AGENT_KVS = {'alive': True,
                 'configurations': GOOD_CONFIGS,
                 'host': 'host',
                 'agent_type': kconst.AGENT_TYPE_KVS}

    AGENTS_DEAD = [{'alive': False,
                    'configurations': GOOD_CONFIGS,
                    'host': 'dead_host'}]
    AGENTS_BAD = [{'alive': False,
                   'configurations': GOOD_CONFIGS,
                   'host': 'bad_host_1'},
                  {'alive': True,
                   'configurations': BAD_CONFIGS,
                   'host': 'bad_host_2'}]

    FAKE_SEGMENTS = [{api.ID: 'unknown_segment_id',
                      api.NETWORK_TYPE: 'unkown_network_type',
                      api.NETWORK_ID: 'fake_network_id'},
                     {api.ID: 'vlan_segment_id',
                      api.NETWORK_TYPE: 'kaloom_knid',
                      api.PHYSICAL_NETWORK: 'fake_physical_network',
                      api.SEGMENTATION_ID: 1234,
                      api.NETWORK_ID: 'fake_network_id'}]

    @patch.object(KaloomNetconf, 'get_vfabric_version', fake_get_vfabric_version)
    def setUp(self):
        super(KaloomMechanismDriverTestCase, self).setUp()
        engine = db_api.get_writer_session().connection().engine
        KaloomKnidMapping.__table__.create(bind=engine)
        KaloomVlanHostMapping.__table__.create(bind=engine)
        with patch.object(KaloomVlanPool, '_parse_network_vlan_ranges', return_value=(1,4094)):
           self.driver_ovs = KaloomOVSMechanismDriver()
           self.driver_ovs.initialize()
           self.driver_kvs = KaloomKVSMechanismDriver()
           self.driver_kvs.initialize()

    def tearDown(self):
        super(KaloomMechanismDriverTestCase, self).tearDown()
        engine = db_api.get_writer_session().connection().engine
        KaloomKnidMapping.__table__.drop(bind=engine)
        KaloomVlanHostMapping.__table__.drop(bind=engine)

    @patch.object(KaloomOVSMechanismDriver, 'try_to_bind_segment_for_agent', return_value=True)
    def test_bind_port_ovs(self, b):
        context = base.FakePortContext(nconst.AGENT_TYPE_OVS,
                                       [self.AGENT_OVS],
                                       self.FAKE_SEGMENTS)
        log_calls = [call("bind_port: Found OVS type agent, Using OVS specific logic")]

        with patch.object(LOG, 'info') as log_info_call:
            self.driver_ovs.bind_port(context)
            log_info_call.assert_has_calls(log_calls)

    @patch.object(KaloomKVSMechanismDriver, 'try_to_bind_segment_for_agent', return_value=True)
    def test_bind_port_kvs(self, b):
        context = base.FakePortContext(kconst.AGENT_TYPE_KVS,
                                       [self.AGENT_KVS],
                                       self.FAKE_SEGMENTS)
        log_calls = [call("bind_port: Found KVS type agent, Using KVS specific logic") ]

        with patch.object(LOG, 'info') as log_info_call:
            self.driver_kvs.bind_port(context)
            log_info_call.assert_has_calls(log_calls)
        # assert False
