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

import sys
import random
from neutron.plugins.common import utils as plugin_utils
from networking_kaloom.ml2.drivers.kaloom.db import kaloom_db
from networking_kaloom.ml2.drivers.kaloom.common import constants as kconst
from oslo_config import cfg
from oslo_log import log
from oslo_db import exception as db_exc

LOG = log.getLogger(__name__)


class KaloomVlanPool(object):
    """
    Find an available vlan on that host
    """
    def __init__(self):
        (self.start, self.end) = self._parse_network_vlan_ranges()

    def _parse_network_vlan_ranges(self):
        try:
            network_vlan_ranges = plugin_utils.parse_network_vlan_ranges(
                cfg.CONF.ml2_type_vlan.network_vlan_ranges)
            # OrderedDict([('provider', [])])
            # OrderedDict([('provider', [(100, 1000)])])

            LOG.info("Network VLAN ranges: %s", network_vlan_ranges)
            # process vlan ranges for first physical network, others are ignored.
            _, vlan_ranges = network_vlan_ranges.items()[0]
            if len(vlan_ranges) == 0:
                 start = kconst.MIN_VLAN_ID
                 end = kconst.MAX_VLAN_ID
            else:
                 start, end = vlan_ranges[0]
            return (start, end)
        except Exception as e:
            LOG.error("Failed to parse network_vlan_ranges. Service terminated! err:%s", e)
            sys.exit(1)

    def _get_available_vlans(self, host):
        available_vlans = range(self.start, self.end + 1)
        all_host_mappings = kaloom_db.get_all_vlan_mappings_for_host(host)
        for m in all_host_mappings:
            try:
                available_vlans.remove(m.vlan_id)
            except ValueError:
                pass
        return available_vlans

    def allocate_local_vlan(self, host, network_id):
        # pick a random value among available vlans
        available_vlans = self._get_available_vlans(host)
        
        while len(available_vlans) > 0 :
            value = random.choice(available_vlans)
            try:
                # check if this is available
                kaloom_db.create_vlan_reservation(host, value, network_id)
                return value
            except db_exc.DBDuplicateEntry:
                # if not remove from the list and try again
                LOG.info("race condition for vlan allocation on %s for network %s, vlan %d has been taken by another process.", host, network_id, value)
                available_vlans.remove(value)

        LOG.warning("Out of available vlans on host %s to attach network %s", host, network_id)
        return None
