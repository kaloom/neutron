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

from neutron.objects.plugins.ml2 import vlanallocation as vlanalloc
from neutron.plugins.ml2.drivers import helpers
from neutron_lib.plugins.ml2 import api
from oslo_log import log

from networking_kaloom.ml2.drivers.kaloom.common import constants as kconst
from networking_kaloom.ml2.drivers.kaloom.mech_driver import pool

LOG = log.getLogger(__name__)


class KaloomKnidTypeDriver(helpers.SegmentTypeDriver):
    """Manage state for kaloom KNID networks with ML2.

    The KaloomKnidTypeDriver implements the 'kaloom_knid' network_type. KNID
    network segments provide connectivity between VMs and other
    devices using connected kaloom kvs switch segmented into virtual
    networks via kaloom KNID headers.
    """

    def __init__(self):
        super(KaloomKnidTypeDriver, self).__init__(vlanalloc.VlanAllocation)

    def get_type(self):
        return kconst.TYPE_KNID

    def initialize(self):
        pass
    
    def validate_provider_segment(self, segment):
        return super(KaloomKnidTypeDriver, self).validate_provider_segment(segment)

    def reserve_provider_segment(self, context, segment, filters=None):
        # no need of local lookup table for knid, depends on vfabric.
        # set to 0. It will be updated to knid once network created in vFabric.
        segmentation_id = 0
        ret = {api.NETWORK_TYPE: kconst.TYPE_KNID,
               api.PHYSICAL_NETWORK: kconst.DEFAULT_PHYSICAL_NETWORK,
               api.SEGMENTATION_ID: segmentation_id,
               api.MTU: kconst.DEFAULT_MTU}
        LOG.debug("Reserved kaloom provider segment with segmentation ID %d " % segmentation_id)
        return ret

    def allocate_tenant_segment(self, context, filters=None):
        # no need of local lookup table for knid, depends on vfabric.
        # set to 0. It will be updated to knid once network created in vFabric.
        segmentation_id = 0
        ret = {api.NETWORK_TYPE: kconst.TYPE_KNID,
               api.PHYSICAL_NETWORK: kconst.DEFAULT_PHYSICAL_NETWORK,
               api.SEGMENTATION_ID: segmentation_id,
               api.MTU: kconst.DEFAULT_MTU}
        LOG.debug("Reserved kaloom tenant segment with segmentation ID %d " % segmentation_id)
        return ret

    def release_segment(self, context, segment):
        # no need to keep track of knid, as lookup depends on vfabric.
        pass

    def get_mtu(self, physical_network=None):
        return kconst.DEFAULT_MTU

    def is_partial_segment(self, segment):
        return False

    def initialize_network_segment_range_support(self):
        pass

    def update_network_segment_range_allocations(self):
        pass

    def get_network_segment_ranges(self):
        pass
