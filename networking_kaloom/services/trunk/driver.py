# Copyright 2019 Kaloom, Inc.  All rights reserved.
# Copyright 2016 Hewlett Packard Enterprise Development LP
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
from neutron_lib.api.definitions import portbindings
from oslo_config import cfg
from oslo_log import log as logging

from neutron.services.trunk import constants as trunk_consts
from neutron.services.trunk.drivers import base
from networking_kaloom.ml2.drivers.kaloom.agent.common import constants as a_const

LOG = logging.getLogger(__name__)

NAME = 'kaloom'
SUPPORTED_INTERFACES = (
    portbindings.VIF_TYPE_VHOST_USER,
)

SUPPORTED_SEGMENTATION_TYPES = (
    trunk_consts.VLAN,
)

class KVSDriver(base.DriverBase):
    """Server-side Trunk driver for the kaloom KVS."""
    @property
    def is_loaded(self):
        try:
            return NAME in cfg.CONF.ml2.mechanism_drivers
        except cfg.NoSuchOptError:
            return False

    @classmethod
    def create(cls):
        return KVSDriver(NAME,
                         SUPPORTED_INTERFACES,
                         SUPPORTED_SEGMENTATION_TYPES,
                         a_const.AGENT_TYPE_KALOOM_KVS)


def register():
    """Register the driver."""
    KVSDriver.create()
    LOG.info('Kaloom KVS trunk driver registered')
