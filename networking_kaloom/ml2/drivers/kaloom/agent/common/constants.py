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

AGENT_TYPE_KALOOM_KVS = 'Kaloom KVS agent'

VIF_TYPE_KALOOM_KVS = 'kvs'

KVS_AGENT_BINARY = "neutron-kaloom-agent"
EXTENSION_DRIVER_TYPE="kaloomkvs"
VHOST_USER_KVS_PLUG = 'vhostuser_kvs_plug'
KVS_SERVER= 'localhost:10515'
KVS_VHOSTUSER_PREFIX = 'vhu'
RESOURCE_ID_LENGTH = 11
TOPIC_KNID = "KNID"
KVS_KNID="knid"
KVS_MAC = "MAC"
KVS_PARENT_PORT_ID= "PORT_ID"

##kvs gRPC error codes
noError = 0
AlreadyExists =1
DoesNotExist = 2
MaxExceeded = 3
PortNotAttached =4
PortAlreadyAttached = 5
FabricRequestFailed= 6
NotJoined = 7
InvalidOperation = 8
InvalidArgument = 9
RPCError= 10
UnexpectedError = 11
