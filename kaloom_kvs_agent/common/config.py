# Copyright 2019 Kaloom, Inc.  All rights reserved.
# Copyright 2012 Cisco Systems, Inc.  All rights reserved.
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

from oslo_config import cfg

DEFAULT_INTERFACE_MAPPINGS = []
DEFAULT_BRIDGE_MAPPINGS = []

kaloom_kvs_opts = [
      cfg.ListOpt('bridge_mappings',
                  default=DEFAULT_BRIDGE_MAPPINGS,
                  help=_("Comma-separated list of "
                       "provider:<kvs> tuples")),
      cfg.StrOpt('vhostuser_socket_dir', default="/var/run",
                  help=_("vhostuser socket dir")),
      ]

def register_kaloomkvs_opts(cfg=cfg.CONF):
    cfg.register_opts(kaloom_kvs_opts, group='kaloom_kvs')
