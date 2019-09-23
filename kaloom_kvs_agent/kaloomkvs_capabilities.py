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

from kaloom_kvs_agent.common \
     import constants as a_const

from neutron.plugins.ml2.drivers.agent import capabilities
from kaloom_kvs_agent.services.trunk import driver

def register():
    """Register Kaloom KVS capabilities."""
    # Add capabilities to be loaded during agent initialization
    # trunk-supported
    capabilities.register(driver.init_handler,
                          a_const.AGENT_TYPE_KALOOM_KVS)

