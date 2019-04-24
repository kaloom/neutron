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

from neutron_lib.plugins import directory
from neutron_lib import context as nctx
from networking_kaloom.ml2.drivers.kaloom.db import kaloom_db
from oslo_db import exception as db_exc
from eventlet import greenthread
from oslo_log import log

LOG = log.getLogger(__name__)

def _get_network_name(network_id):
    ctx = nctx.get_admin_context()
    return directory.get_plugin().get_network(ctx, network_id)['name'] 

def _kaloom_nw_name(prefix, network_id, name):
    """Generate an kaloom specific name for this network.

    Use a unique name so that OpenStack created networks
    can be distinguishged from the user created networks
    on Kaloom vFabric. Replace spaces with underscores for CLI compatibility
    """
    ##until nw rename (openstack network set) not captured in ML2, dont use name in vfabric GUI.
    #return prefix + network_id + '.' + name.replace(' ', '_')
    return prefix + network_id

def tp_operation_lock(host, network_id):
    """ concurrent attachments, detachments, attachments/detachments, detachments/attachments 
    of neutron ports on same (host, network_id) pair conflicts with vfabric TP attach/detach.
    Concurrent attachments of multiple neutron ports on the same host/network should result in single
    TP attachment. While concurrent detachments of multiple neutron ports of the same host/network occuring,
    last neutron port delete should result in the TP detach. On concurrent attachments and detachments of multiple
    neutron ports on the same host/network, TP attachment should remain until there is single neutron port remained.

    This is applied simply by using lock mechanism on tp_operation per host/network_id. Any attach and detach neutron port
    requires to acquire the lock.
    """
    tries = 1 
    iterations = 10
    retry_interval = 0.5
    while tries <= iterations:
           try:
               kaloom_db.create_tp_operation(host, network_id)
               LOG.debug('tp_operation_lock acquired for host=%s, network_id=%s on tries %s', host, network_id, tries)
               return True
           except db_exc.DBDuplicateEntry as e:
               tries += 1
               greenthread.sleep(retry_interval)
    LOG.warning('tp_operation_lock is not acquired for host=%s, network_id=%s on tries %s', host, network_id, tries-1)
    return False


def tp_operation_unlock(host, network_id):
    kaloom_db.delete_tp_operation(host, network_id)
    LOG.debug('tp_operation_unlock for host=%s, network_id=%s', host, network_id)

