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

from oslo_config import cfg

kaloom_cfg_opts = [
    cfg.StrOpt('kaloom_host', default="127.0.0.1",
               help="Kaloom VFabric Controller host IP"),
    cfg.IntOpt('kaloom_port', default=31831,
               help="Kaloom VFabric Controller netconf port"),
    cfg.StrOpt('kaloom_username', default="admin",
               help="Kaloom VFabric Controller username"),
    cfg.StrOpt('kaloom_private_key_file', default="",
               help="Kaloom private-key file to authenticate to VFabric Controller"),
    cfg.StrOpt('kaloom_password', default="admin",
               help="Kaloom password to authenticate to VFabric controller (as fallback)"),
    cfg.IntOpt('l3_sync_interval', default=180,
               help="Sync interval in seconds between L3 Service plugin and vFabric"),
]


def register_opts():
    cfg.CONF.register_opts(kaloom_cfg_opts, "KALOOM")
