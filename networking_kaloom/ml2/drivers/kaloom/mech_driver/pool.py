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
from neutron.plugins.common import utils as plugin_utils
from bitarray import bitarray
from networking_kaloom.ml2.drivers.kaloom.db import kaloom_db
from networking_kaloom.ml2.drivers.kaloom.common import constants as kconst
from oslo_config import cfg
from oslo_log import log
from oslo_db import exception as db_exc

LOG = log.getLogger(__name__)


class IdPool(object):
    def __init__(self, start, end):
        self.start = start
        self.end = end
        self.allocation_bitmap = bitarray(end)

    def allocate(self, host, network_id):
        self.refresh(host)
        done = False  
        while not done:
           try:
               value = self.allocation_bitmap.index(False, self.start, self.end)
           except ValueError as e:
               LOG.warning('All vlans exhausted, when trying for host:network=%s:%s', host, network_id)
               return None

           #handling race condition among controllers.
           #whoever gets (host,vlan) key violation tries next available. 
           try:
               kaloom_db.create_vlan_reservation(host, value, network_id)
               done = True
           except db_exc.DBDuplicateEntry as e:
               LOG.warning('Race condition on vlan allocation(host:%s, vlan:%s), msg:%s, Trying another.', host, value, e)
               self.allocation_bitmap[value] = True

        return value


    def release(self, host, key):
        # no tracking done
        pass

    def refresh(self, host):
        self.allocation_bitmap.setall(False)
        all_host_mappings = kaloom_db.get_all_vlan_mappings_for_host(host)
        for m in all_host_mappings:
           self.allocation_bitmap[m.vlan_id] = True

class KaloomVlanPool(IdPool):
    """
    Maps from a tuple of network-id and host to a VLAN
    """
    def __init__(self):
        (start, end) = self._parse_network_vlan_ranges()
        super(KaloomVlanPool, self).__init__(start, end)

    def _parse_network_vlan_ranges(self):
        try:
            network_vlan_ranges = plugin_utils.parse_network_vlan_ranges(
                cfg.CONF.ml2_type_vlan.network_vlan_ranges)
            # OrderedDict([('provider', [])])
            # OrderedDict([('provider', [(100, 1000)])])

            LOG.info("Network VLAN ranges: %s", network_vlan_ranges)
            # process vlan ranges for first physical network, others are ignored.
            physical_network, vlan_ranges = network_vlan_ranges.items()[0]
            if len(vlan_ranges) == 0:
                 start = kconst.MIN_VLAN_ID
                 end = kconst.MAX_VLAN_ID
            else:
                 start, end = vlan_ranges[0]
            return (start, end)
        except Exception:
            LOG.exception("Failed to parse network_vlan_ranges. "
                          "Service terminated!")
            sys.exit(1)

    def allocate_local_vlan(self, host, network_id):
        return super(KaloomVlanPool, self).allocate(host, network_id)

    def release_local_vlan(self, host, local_vlan_id):
        return super(KaloomVlanPool, self).release(host, local_vlan_id)

