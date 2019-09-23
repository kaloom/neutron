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

PLUGIN_NAME = 'ovs'

KVS_VHOSTUSER_INTERFACE_TYPE = 'dpdkvhostuser'
KVS_VHOSTUSER_CLIENT_INTERFACE_TYPE = 'dpdkvhostuserclient'
KVS_VHOSTUSER_PREFIX = 'vhu'

KVS_DATAPATH_SYSTEM = 'system'
KVS_DATAPATH_NETDEV = 'netdev'
KVS_SERVER= 'localhost:10515'
VHOST_SOCK_OWNER = 'qemu:kvm'
VHOST_SOCK_PERM = '0664'

KVS_VHOSTUSER_PREFIX = 'vhu'
TOPIC_KNID = "KNID"
KVS_KNID="knid"

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
