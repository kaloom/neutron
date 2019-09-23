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

TYPE_KNID = "kaloom_knid"
DEFAULT_MTU = 1500
DEFAULT_PHYSICAL_NETWORK = "provider"
AGENT_TYPE_KVS = 'Kaloom KVS agent'

DEFAULT_VLAN_ID = 1
MIN_VLAN_ID = 2
MAX_VLAN_ID = 4094
MIN_SEGMENT_ID = 2
MAX_SEGMENT_ID = 2 ** 32 - 1

VLAN_POOL_LOCK = 'kaloom_vlan_pool_lock'
SEGMENT_POOL_LOCK= 'kaloom_segment_pool_lock'
MSGID_LOCK = 'kaloom_netconf_msgid_lock'
SESSION_INIT_LOCK = 'kaloom_netconf_session_init_lock' 

