# Copyright 2019 Kaloom, Inc.  All rights reserved.
# Copyright (c) 2013 OpenStack Foundation
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

import os
import signal
import abc, six

from oslo_log import log
from oslo_config import cfg
from neutron_lib import constants
from neutron.plugins.ml2.drivers.openvswitch.mech_driver.mech_openvswitch import OpenvswitchMechanismDriver
from neutron.plugins.ml2.common import exceptions as ml2_exc
from neutron_lib import exceptions as n_exc
from neutron_lib.api.definitions import portbindings, provider_net
from neutron.services.segments import plugin as segments_plugin
from networking_kaloom.ml2.drivers.kaloom.mech_driver import pool
from networking_kaloom.ml2.drivers.kaloom.db import kaloom_db
from networking_kaloom.ml2.drivers.kaloom.common.kaloom_netconf import KaloomNetconf
from networking_kaloom.ml2.drivers.kaloom.common import config as kaloom_config
from networking_kaloom.ml2.drivers.kaloom.common import constants as kconst
from networking_kaloom.ml2.drivers.kaloom.common import utils
from networking_kaloom.ml2.drivers.kaloom.agent.common import constants as a_const
from oslo_utils import uuidutils
from neutron.objects import network as network_obj
from neutron.db import api as db_api
from neutron.common import rpc as common_rpc
from neutron.common import topics
from networking_kaloom.ml2.drivers.kaloom.mech_driver import kvs_rpc
from networking_kaloom.services.trunk import driver as kvs_trunk_driver
from neutron_lib import worker
from oslo_service import loopingcall, service
from neutron_lib import context as nctx
import sqlalchemy.orm.exc as sa_exc

LOG = log.getLogger(__name__)

kaloom_config.register_opts()

def clean_local_vlan_mappings(network_id):
    """ When a network is deleted, remove all residual mappings for Local VLAN """
    mappings = kaloom_db.get_all_vlan_mappings_for_network(network_id)
    for m in mappings:
       kaloom_db.delete_host_vlan_mapping(network_id=m.network_id,
                                               host=m.host)
    #clear record on vlan reservation 
    mappings = kaloom_db.get_all_vlan_reservations_for_network(network_id)
    for m in mappings:
       kaloom_db.delete_vlan_reservation(host=m.host, vlan_id=m.vlan_id)

def remove_local_vlan_mapping(local_vlan_mapping):
    if local_vlan_mapping:
       kaloom_db.delete_host_vlan_mapping(network_id=local_vlan_mapping.network_id, host=local_vlan_mapping.host)
       #clear record on vlan reservation
       kaloom_db.delete_vlan_reservation(host=local_vlan_mapping.host, vlan_id=local_vlan_mapping.vlan_id)

def remove_local_segment(context, segment_id):
    with db_api.context_manager.writer.using(context):
       try:
          netseg_obj = network_obj.NetworkSegment.get_object(context, id=segment_id)
          if netseg_obj:
             netseg_obj.delete()
       except sa_exc.StaleDataError: #ignore concurrent delete
          pass
       except Exception as e:
          LOG.warning('caught on remove_local_segment segment_id: %s, errmsg: %s', segment_id, e)

class Singleton(abc.ABCMeta):
    _instances = {}
    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]

@six.add_metaclass(Singleton)
class KaloomL2CleanupWorker(worker.BaseWorker):
    def __init__(self, vfabric, prefix):
        self.vfabric = vfabric
        self.prefix = prefix
        self._loop = None
        self.deleting_seconds = self.interval_seconds = 10
        self.creating_seconds = 60
        super(KaloomL2CleanupWorker, self).__init__(worker_process_count=1)

    def start(self):
        super(KaloomL2CleanupWorker, self).start()
        if self._loop is None:
           self._loop = loopingcall.FixedIntervalLoopingCall(self.cleanup)
           self._loop.start(interval = self.interval_seconds, initial_delay=self.interval_seconds) #delayed start to complete service loading in init

    def stop(self):
        if self._loop is not None:
            self._loop.stop()

    def wait(self):
        if self._loop is not None:
            self._loop.wait()
        self._loop = None

    def reset(self):
        self.stop()
        self.wait()
        self.start()

    def cleanup(self):
        LOG.debug('cleanup..')
        #clean stranded networks in vfabric, that does not exist in openstack: e.g. created after netconf timeout, manually created.
        try:
           networks = kaloom_db.get_networks()
           openstack_nw_names = []
           for network in networks:
              nw_name = utils._kaloom_nw_name(self.prefix, network.id)
              openstack_nw_names.append(nw_name)
           vfabric_nw_names = self.vfabric.get_l2_network_names(self.prefix)
           stranded_nw_names = set(vfabric_nw_names) - set(openstack_nw_names)
           if len(stranded_nw_names) > 0:
               LOG.info("cleanup found stranded networks: %s, cleaning up..", stranded_nw_names)
           for stranded_nw_name in stranded_nw_names:
               try:
                  network_id = stranded_nw_name.split(self.prefix)[1].split('_')[0] #network_id is in between of prefix and _
                  knid_mapping = kaloom_db.get_knid_mapping(network_id=network_id)
                  if knid_mapping:
                     kaloom_db.delete_knid_mapping(network_id)
                     clean_local_vlan_mappings(network_id)

                  self.vfabric.delete_l2_network(stranded_nw_name)
               except Exception as e:
                  LOG.warning("cleanup failed to delete stranded l2_network:%s in vfabric, err:%s", stranded_nw_name, e)
        except Exception as e:
           LOG.warning("cleanup stranded networks: error caught err_msg:%s", e)

        #clean stranded tp-attachment
        try:
           all_stale_vlan_mappings = kaloom_db.get_stale_vlan_mappings(self.creating_seconds, self.deleting_seconds)
        except Exception as e:
           LOG.warning("cleanup stranded tp-attachment: error caught err_msg:%s", e)
           return

        if all_stale_vlan_mappings:
           ctx = nctx.get_admin_context()
           for m in all_stale_vlan_mappings:
              try:
                 LOG.info('Cleaning.. for host=%s network=%s vlan=%s state=%s timestamp:%s', m.host, m.network_id, m.vlan_id, m.state, m.timestamp)
                 tp = self.vfabric.get_tp_by_annotation(m.host)
                 if tp:
                    self.vfabric.detach_tp_from_l2_network(m.network_name, tp.get('id'))
                 remove_local_segment(ctx, m.segment_id)
                 remove_local_vlan_mapping(m)
              except Exception as e:
                 LOG.warning("cleanup: error caught for host=%s, network=%s err_msg:%s", m.host, m.network_id, e)

class KaloomOVSMechanismDriver(OpenvswitchMechanismDriver):
    """
    OVS mechanism driver for Kaloom. Extends the default
    OVS driver and then does a post commit operation to
    set the correct VNI
    """

    def __init__(self):
        LOG.info("%s __init__ called", self._plugin_name())
        self.segments_plugin = segments_plugin.Plugin.get_instance()
        self.prefix = '__OpenStack__'
        super(KaloomOVSMechanismDriver, self).__init__()
        self.initialize()
        self.cleanup.start()
        self._handle_signal()

    def _plugin_name(self):
        #returns KaloomOVSMechanismDriver or KaloomKVSMechanismDriver
        return type(self).__name__

    def initialize(self):
        self.vlan_pool = pool.KaloomVlanPool()
        self.vfabric = KaloomNetconf(cfg.CONF.KALOOM.kaloom_host,
                                    cfg.CONF.KALOOM.kaloom_port,
                                    cfg.CONF.KALOOM.kaloom_username,
                                    cfg.CONF.KALOOM.kaloom_private_key_file,
                                    cfg.CONF.KALOOM.kaloom_password)
        self.cleanup = KaloomL2CleanupWorker(self.vfabric, self.prefix)

    def _handle_signal(self):
        signal_handler = service.SignalHandler()
        signal_handler.add_handler('SIGTERM', self._handle_sigterm)
        signal_handler.add_handler('SIGHUP', self._handle_sighup)

    def _handle_sigterm(self, signum, frame):
        LOG.info("%s caught SIGTERM, stopping l2-cleanup and netconf-receiver threads", self._plugin_name())
        self.cleanup.stop()
        if self.vfabric.receiver.is_running():
           self.vfabric.receiver.stop(graceful = False)

    #'systemctl reload neutron-server' is not supported, still we want to be compatible with 'kill -SIGHUP'
    #'reset' is not called in ML2 plugin, when there is 'reset' in oslo_service (neutron-server).
    # custom SIGHUP handler
    def _handle_sighup(self, signum, frame):
        LOG.info("%s caught SIGHUP, resetting l2-cleanup  and netconf-receiver threads", self._plugin_name())
        #stopping
        self.cleanup.stop()
        self.cleanup.wait()
        if self.vfabric.receiver.is_running():
           self.vfabric.receiver.stop()
           self.vfabric.receiver.wait()
        #reload configuration files
        cfg.CONF.reload_config_files()
        #re-initialize
        self.initialize()
        #start cleanup
        self.cleanup.start()
        #don't start netconf-receiver here, start will be on add_callback_event, when first msg appears

    def get_kvs_vif_type(self, context, agent, segment):
        device_owner = context.current['device_owner']
        if device_owner.startswith(constants.DEVICE_OWNER_COMPUTE_PREFIX):
            return portbindings.VIF_TYPE_VHOST_USER
        return a_const.VIF_TYPE_KALOOM_KVS

    def get_kvs_vif_details(self, context, agent, segment):
        vif_details = self._pre_get_kvs_vif_details(agent, context)
        return vif_details

    def _pre_get_kvs_vif_details(self, agent, context):
        vif_type = self.get_kvs_vif_type(context, agent, segment=None)
        if vif_type != portbindings.VIF_TYPE_VHOST_USER:
            details = { portbindings.CAP_PORT_FILTER: True }
        else:
            sock_path = self.kvs_agent_vhu_sockpath(agent, context.current['id'])
            mode = portbindings.VHOST_USER_MODE_CLIENT
            details = {portbindings.CAP_PORT_FILTER: False,
                       a_const.VHOST_USER_KVS_PLUG: True,
                       portbindings.VHOST_USER_MODE: mode,
                       portbindings.VHOST_USER_SOCKET: sock_path}
        return details

    @staticmethod
    def kvs_agent_vhu_sockpath(agent, port_id):
        """
        Return the agent's vhost-user socket path for a given port.

        OVS restricts 14 char length vhost sock_name but allows to set port_id
        property on port and the port_id is used rather than (truncated) sockpath
        to sync with neutron.

        KVS do not have option to set port_id but supports full length sockpath. So
        port_id will be derived from un-truncated sockpath, and will be used to
        sync with neutron.
        """
        sockdir = agent['configurations'].get('vhostuser_socket_dir','')
        sock_name = (constants.VHOST_USER_DEVICE_PREFIX + port_id)
        return os.path.join(sockdir, sock_name)

    def get_allowed_network_types(self, agent):
        if agent['agent_type'] in [a_const.AGENT_TYPE_KALOOM_KVS, constants.AGENT_TYPE_OVS]:
            return [kconst.TYPE_KNID]

    #all mech-drivers are called for bind_port
    def bind_port(self, context):
        ovs_present = self._is_ovs_agent_present(context)
        kvs_present = self._is_kvs_agent_present(context)
        #kaloom_kvs plugin sees kvs presence
        if self.agent_type == a_const.AGENT_TYPE_KALOOM_KVS and kvs_present:
           LOG.info("bind_port: Found KVS type agent, Using KVS specific logic")
           super(KaloomOVSMechanismDriver, self).bind_port(context)
        #kaloom_ovs plugin sees ovs presence
        #in case kvs is also present, let the kaloom_kvs plugin to handle binding.
        elif self.agent_type == constants.AGENT_TYPE_OVS and ovs_present and not kvs_present:
           LOG.info("bind_port: Found OVS type agent, Using OVS specific logic")
           super(KaloomOVSMechanismDriver, self).bind_port(context)

    def try_to_bind_segment_for_agent(self, context, segment, agent):
        if self.check_segment_for_agent(segment, agent):#check for allowed_network_types
            if agent['agent_type'] == a_const.AGENT_TYPE_KALOOM_KVS:
                return self._try_to_bind_segment_kvs_agent(context, segment, agent)
            elif agent['agent_type'] == constants.AGENT_TYPE_OVS:
                return self._try_to_bind_segment_ovs_agent(context, segment, agent)

        return False

    def _try_to_bind_segment_ovs_agent(self, context, segment, agent):
        network_id = segment.get('network_id')
        host = context.current.get('binding:host_id')
        try:
          nw_name = utils._kaloom_nw_name(self.prefix, network_id)
          local_vlan_mapping = kaloom_db.get_vlan_mapping_for_network_and_host(network_id, host)
          #There could be concurrent ports deletion leading to tp_detach
          if local_vlan_mapping is None: ## None implicitly means 'DELETED' state or doesnot exist
              msg = 'can not bind as vlan mapping doesnot exist.'
              raise ValueError(msg)
          if local_vlan_mapping.state == 'DELETING':
              #DELETING: deletion ongoing or never finished.
              msg = 'can not bind as vlan mapping state: %s, deletion ongoing' % local_vlan_mapping.state
              raise ValueError(msg)
          if local_vlan_mapping.state == 'CREATING': #concurrent tp_attach has been allowed.
              try:
                 tp_id = self.vfabric.get_tp_by_annotation(host).get('id')
              except Exception as e:
                 msg = "Error on get_tp_by_annotation for host %s: %s" % (host, e)
                 raise ValueError(msg)
              attach_name = '%s:%s' % (network_id, tp_id)
              local_vlan_id = local_vlan_mapping.vlan_id
              try:
                  self.vfabric.attach_tp_to_l2_network(nw_name, attach_name, tp_id, local_vlan_id)
              except Exception as e: 
                  ##duplicate should not raise error.
                  if "unique duplicate constraint" not in str(e):
                      msg = "Error on attach_tp_to_l2_network for tpid %s vlan %s nw %s: %s" % (tp_id, local_vlan_id, nw_name, e)
                      raise ValueError(msg)

          local_vlan_id = local_vlan_mapping.vlan_id
          local_seg_id = local_vlan_mapping.segment_id
          original_state = local_vlan_mapping.state
          if original_state == 'CREATING':
              new_state = 'CREATED'
          else:
              new_state = original_state
          if new_state != original_state:
              status = kaloom_db.update_state_on_network_host_vlan_mapping(network_id=network_id, host=host, state=new_state)
              if not status: # concurrent deletion of "last port" already happened.
                  #rollback and raise error
                  self.vfabric.detach_tp_from_l2_network(nw_name, tp_id)
                  raise ValueError('concurrent deletion happened.')
          ##
          context.set_binding(local_seg_id,
                              self.get_vif_type(context, agent, segment),
                              self.get_vif_details(context, agent, segment))
          LOG.info("state: %s -> %s, PORT BINDED on SEGMENT=%s, VLAN=%d of host=%s, network=%s" % (original_state, new_state, local_seg_id, local_vlan_id, host, network_id))
          return True
        except Exception as e:
            LOG.error("Error during bind_port on OVS host=%s, network=%s, err_msg:%s", host, network_id, e)
            return False

    def _allocate_local_vlan_mapping(self, context, network_id, host, physical_network, nw_name):
        local_vlan_id = self.vlan_pool.allocate_local_vlan(host, network_id)
        if local_vlan_id is None:
            return None
        local_seg = self._create_segment(context._plugin_context, network_id,
                                         physical_network, 'vlan',
                                         local_vlan_id, 1, context.host, False)
        try:
            kaloom_db.create_network_host_vlan_mapping(network_id, host, local_seg.get('id'), local_vlan_id, nw_name)
        except Exception as e:
            LOG.error("Error create_network_host_vlan_mapping VLAN=%d for host=%s, network=%s, err_msg: %s", local_vlan_id, host, network_id, e)
            #clear record on vlan reservation
            kaloom_db.delete_vlan_reservation(host=host, vlan_id=local_vlan_id)
            return None

        LOG.info("LOCAL VLAN NOT FOUND: ALLOCATING VLAN %d for host=%s, network=%s" %
                 (local_vlan_id, host, network_id))
        local_vlan_mapping = type('local_vlan_mapping', (object,), {'vlan_id' : local_vlan_id, 'segment_id': local_seg.get('id'), 'state':'CREATING'})
        return local_vlan_mapping

    def _try_to_bind_segment_kvs_agent(self, context, segment, agent):
        network_id = segment.get('network_id')
        host = context.current.get('binding:host_id')
        try:
            segment_id = kaloom_db.get_segment_for_network(network_id).id # None segment raises exception
            vif_details = self.get_kvs_vif_details(context, agent, segment)
            vif_details['knid'] = kaloom_db.get_knid_for_network(network_id)

            context.set_binding(segment_id,
                                self.get_kvs_vif_type(context, agent, segment),
                                vif_details
                                )
            return True
        except Exception as e:
            LOG.error("Error during bind_port on KVS host=%s, network=%s, err_msg:%s", host, network_id, e)
            return False

    #All mech drivers are called upon create/update/delete_port/network_precommit/postcommit.
    #act only for allowed network_type.
    def _is_network_type_allowed(self, nw_ctx):
        network_type = nw_ctx.current.get(provider_net.NETWORK_TYPE)
        if network_type is None:
            segments = nw_ctx.current.get('segments')
            if segments is not None and len(segments) > 0:
               network_type = segments[0].get(provider_net.NETWORK_TYPE)
        return network_type in self.get_allowed_network_types(agent={'agent_type': self.agent_type})

    # Called inside transaction context on session. Raising an exception will result in a rollback of the current transaction
    def create_port_precommit(self, context):
        #not allowed network_type or kaloom_kvs plugin or in case of kaloom_ovs plugin host not available for device owner compute:nova
        if not self._is_network_type_allowed(context.network) or self.agent_type == a_const.AGENT_TYPE_KALOOM_KVS or context.host is None:
            super(KaloomOVSMechanismDriver, self).create_port_precommit(context)
            return
        #host is available for device_owner dhcp
        self._create_local_vlan_mapping(context, call_from='create_port_precommit') #super will be called by create_local_vlan_mapping

    # for device_owner compute:nova, binding host is not available on create_port_*, only available on update_port_* and bind_port.
    #       after create_port_*, update_port_* get called to update binding: _original_port{'binding:host_id': '', device_owner': '' 'binding:vif_type': 'unbound'} ->  _port{'binding:host_id': 'os-controller', 'device_owner': 'compute:nova', 'binding:vif_type': 'unbound'}
    #       then bind_port get called.
    # For dhcp owner: binding host is available even on create_port_*.
    #       after create_port_*, bind_port get called.
    # bind_port further could trigger update_port_*, for e.g to update status of 'binding:vif_type'.
    # Called inside transaction context on session. Raising an exception will result in a rollback of the current transaction
    def update_port_precommit(self, context):
        #not allowed network_type or kaloom_kvs plugin
        if not self._is_network_type_allowed(context.network) or self.agent_type == a_const.AGENT_TYPE_KALOOM_KVS:
            super(KaloomOVSMechanismDriver, self).update_port_precommit(context)
            return
        #kaloom_ovs plugin
        original_host = context._original_port.get('binding:host_id')
        current_host = context.host
        if current_host and current_host != original_host:
             # original_host '' -> current_host 'hostx': happens on port_binding after create_port for device_owner compute:nova
             # original_host 'hostx' -> current_host 'hosty' : happens on port migration 
             self._create_local_vlan_mapping(context, call_from='update_port_precommit') #super will be called by create_local_vlan_mapping
        else:
            super(KaloomOVSMechanismDriver, self).update_port_precommit(context)
            return

    def _create_local_vlan_mapping(self, context, call_from):
        try:
          network_id = context.current.get('network_id')
          host = context.host
          getattr(super(KaloomOVSMechanismDriver, self), call_from)(context)
          kvs_present = self._is_kvs_agent_present(context)
          ovs_present = self._is_ovs_agent_present(context)
          if kvs_present:#kaloom_ovs plugin found kvs_present, nothing to do.
              return
          if not ovs_present:
              LOG.warning("%s: KVS/OVS agent is not alive on host=%s, nothing to do.", call_from, host)
              #don't raise to pass tempest test_portbinding_bumps_revision
              return
          #in case of ovs node binding.
          LOG.info("%s: Found OVS type agent, Using OVS specific logic", call_from)
          nw_name = utils._kaloom_nw_name(self.prefix, network_id)
          local_vlan_mapping = kaloom_db.get_vlan_mapping_for_network_and_host(network_id, host)
          if local_vlan_mapping is None:
              physical_network = kaloom_db.get_segment_for_network(network_id).physical_network #None segment raises exception
              #There is no possibility of concurrent tp_detach on delete_port_postcommit, as there is no remaining local_vlan_mapping.
              #lock concurrent attach/detach for vfabric TP 
              if not utils.tp_operation_lock(host, network_id):
                  raise ValueError('Could not get lock.')
              try:
                  #default is state: 'CREATING'
                  local_vlan_mapping = self._allocate_local_vlan_mapping(context, network_id, host, physical_network, nw_name)
              except:
                  pass
              finally:
                  utils.tp_operation_unlock(host, network_id)  #release lock 

              if local_vlan_mapping is None:
                  msg = 'Vlan could not be allocated.'
                  raise ValueError(msg)
          #There could be concurrent ports deletion leading to tp_detach.
          elif local_vlan_mapping.state == 'DELETING':
              #DELETING: deletion ongoing or never finished.
              msg='vlan mapping state:%s exists, another concurrent tp_detach ongoing' % local_vlan_mapping.state
              raise ValueError(msg)
          #or concurrent ports creation leading to tp_attach.
          elif local_vlan_mapping.state == 'CREATING':
              #CREATING: another concurrent tp_attach not finished yet or never finished: try_to_bind anyway (duplicate tp_attach will be handeled.)
              pass
          return
        except Exception as e:
            LOG.error("Error during %s on host=%s, network=%s, err_msg:%s", call_from, host, network_id, e)
            raise ml2_exc.MechanismDriverError(method = call_from, errors = e) #rollback.


    #lock moved to precommit.
    def delete_port_precommit(self, context):
        super(KaloomOVSMechanismDriver, self).delete_port_precommit(context)
        #not allowed network_type
        if not self._is_network_type_allowed(context.network):
            return

        # KVS case, we don't need to do anything
        vif_details = context.current.get('binding:vif_details')
        if 'knid' in vif_details.keys():
            return

        network_id = context.current.get('network_id')
        host = context.host

        #lock concurrent attach/detach for vfabric TP
        if not utils.tp_operation_lock(host, network_id):
            e = "tp_operation_lock failed on delete_port for host=%s, network_id=%s, rollback." % (host, network_id)
            raise ml2_exc.MechanismDriverError(method = 'delete_port_precommit', errors = e)
        try:

          if kaloom_db.get_port_count_for_network_and_host(network_id, host) <= 1: #on port_precommit, last port has not been deleted yet.
              local_vlan_mapping = kaloom_db.get_vlan_mapping_for_network_and_host(network_id, host)
              if local_vlan_mapping is None: #by chance: e.g. manual table cleanup
                  return #goes through "finally"
              if local_vlan_mapping.state in ('CREATING', 'CREATED'):
                  status = kaloom_db.update_state_on_network_host_vlan_mapping(network_id=network_id, host=host, state='DELETING') #tag to delete
                  if not status:
                      LOG.info('delete_port_precommit: failed to update state=DELETING on host=%s, network=%s; ignored.', host, network_id)
        except Exception as e:
            LOG.error("delete_port_precommit: error caught host=%s, network=%s err_msg:%s", host, network_id, e)
            raise ml2_exc.MechanismDriverError(method = 'delete_port_precommit', errors = e)
        finally:
            utils.tp_operation_unlock(host, network_id)  #release lock

    #"openstack network delete .." calls first delete_port* if any on the network, and then calls delete_network*
    #delete_port_postcommit: Runtime errors are not expected, and will not prevent the resource from being deleted.
    #so cleanup as much as possible.
    def delete_port_postcommit(self, context):
        super(KaloomOVSMechanismDriver, self).delete_port_postcommit(context)
        #not allowed network_type
        if not self._is_network_type_allowed(context.network):
            return

        # KVS case, we don't need to do anything
        vif_details = context.current.get('binding:vif_details')
        if 'knid' in vif_details.keys():
            return

        network_id = context.current.get('network_id')
        host = context.host
        if kaloom_db.get_port_count_for_network_and_host(network_id, host) <= 0: #on port_postcommit, last port has been already deleted.
           local_vlan_mapping = kaloom_db.get_vlan_mapping_for_network_and_host(network_id, host)
           if local_vlan_mapping is None: #state:DELETED, concurrent delete, already may have deleted.
               return
           #all concurrent deletes try to cleanup, and changes state 'DELETING' ==> DELETED
           try:   
               local_vlan_id = local_vlan_mapping.vlan_id
               tp = self.vfabric.get_tp_by_annotation(host)
               ##multiple attempts of detach_tp, remove_local_segment, remove_local_vlan_mapping won't raise error.
               if tp:
                  self.vfabric.detach_tp_from_l2_network(local_vlan_mapping.network_name, tp.get('id'))
               #in case vfabric operation successful, release vlan and segment
               LOG.info("Last port on host=%s, network=%s, removing vlan:%s mapping", host, network_id, local_vlan_id)
               remove_local_segment(context._plugin_context, local_vlan_mapping.segment_id)
               remove_local_vlan_mapping(local_vlan_mapping) #'DELETING' ==> DELETED, as the record deleted
           except Exception as e:
               # vlan, and/or tp_attachment may exist: state remained to DELETING.
               LOG.warning("delete_port_postcommit: error caught on last port for host=%s, network=%s err_msg:%s", host, network_id, e)


    #create_network_postcommit "rollbacks" on exception, by calling delete_network*, so extra care needed.
    def create_network_postcommit(self, context):
        super(KaloomOVSMechanismDriver, self).create_network_postcommit(context)
        #not allowed network_type
        if not self._is_network_type_allowed(context):
            return

        network_id = context.current.get('id')
        nw_name = utils._kaloom_nw_name(self.prefix, network_id)
        #create nw in vfabric
        gui_nw_name = utils._kaloom_gui_nw_name(self.prefix, network_id,context.current.get('name'))
        try:
            knid = self.vfabric.create_l2_network(nw_name, gui_nw_name, kconst.DEFAULT_VLAN_ID).get('kaloom_knid')
        except Exception as e:
            ##duplicate should not raise error (TYPE_KNID is used by both kaloom_ovs and kaloom_kvs mech driver)
            if "unique duplicate constraint" in str(e):
               return
            else:
               LOG.error("errors: %s", e)
               #raising an exception will result in rollback of the transaction
               raise ml2_exc.MechanismDriverError(method = 'create_network_postcommit', errors = e)
        LOG.info("Created Kaloom network with KNID %d " % knid)
        kaloom_db.create_knid_mapping(kaloom_knid=knid, network_id=network_id)

    #delete_network_postcommit called after db transaction: the caller ignores the error i.e won't undo the action by recreating the network.
    def delete_network_postcommit(self, context):
        super(KaloomOVSMechanismDriver, self).delete_network_postcommit(context)
        # don't check allowed network_type, as network's segments are deleted before this, resulting network_type=None.
        network_id = context.current.get('id')
        nw_name = utils._kaloom_nw_name(self.prefix, network_id)

        try:
           knid_mapping = kaloom_db.get_knid_mapping(network_id=network_id)
           if knid_mapping: #rollback on create_network_postcommit calls delete_network so the knid_mapping may not exist
               kaloom_db.delete_knid_mapping(network_id)
               clean_local_vlan_mappings(network_id)
           #vfabric network could have been created after netconf timeout on create_l2_network i.e. even in case of non-existing knid_mapping.
           self.vfabric.delete_l2_network(nw_name) #if this fails, cleanup process will take care of stranded vfabric networks. 
        except Exception as e:
            LOG.warning("delete_network_postcommit network:%s err:%s", nw_name, e)
        return

    #to support vfabric nw rename upon: openstack network set --name <new_name> <network>
    def update_network_postcommit(self, context):
        super(KaloomOVSMechanismDriver, self).update_network_postcommit(context)
        #not allowed network_type
        if not self._is_network_type_allowed(context):
            return
        original_name = context.original.get('name')
        current_name = context.current.get('name')
        if current_name != original_name: #nw renamed
           #rename vfabric network gui-name.
           network_id = context.current.get('id')
           nw_name = utils._kaloom_nw_name(self.prefix, network_id)
           current_gui_nw_name = utils._kaloom_gui_nw_name(self.prefix, network_id, current_name)
           try:
              self.vfabric.rename_l2_network(nw_name, current_gui_nw_name)
           except Exception as e:
              LOG.error("errors: %s", e)

    def _is_kvs_agent_present(self, context):
        agents_on_host = context.host_agents(a_const.AGENT_TYPE_KALOOM_KVS)
        for agent in agents_on_host:
            if agent['alive']:
               return True
        return False

    def _is_ovs_agent_present(self, context):
        agents_on_host = context.host_agents(constants.AGENT_TYPE_OVS)
        for agent in agents_on_host:
            if agent['alive']:
               return True
        return False

    def _create_segment(self, context, network_id, physical_network, network_type, segmentation_id, segment_index, host,
                        is_dynamic):
        with db_api.context_manager.writer.using(context):
            netseg_obj = network_obj.NetworkSegment(
                context, id=uuidutils.generate_uuid(), network_id=network_id,
                network_type=network_type,
                physical_network=physical_network,
                segmentation_id=segmentation_id,
                hosts=[host],
                segment_index=segment_index, is_dynamic=is_dynamic)
            netseg_obj.create()

            return self._make_segment_dict(netseg_obj)

    def _make_segment_dict(self, obj):
        """Make a segment dictionary out of an object."""
        return {'id': obj.id,
                'network_type': obj.network_type,
                'physical_network': obj.physical_network,
                'segmentation_id': obj.segmentation_id,
                'network_id': obj.network_id}

class KaloomKVSMechanismDriver(KaloomOVSMechanismDriver):
    """
    KVS Mechanism driver for kaloom, supports agent_type of kvs.
    """
    def __init__(self):
        super(KaloomKVSMechanismDriver, self).__init__()
        self.agent_type = a_const.AGENT_TYPE_KALOOM_KVS
        self.vif_type = a_const.VIF_TYPE_KALOOM_KVS
        self.vif_details = { portbindings.CAP_PORT_FILTER: True }
        #self.supported_vnic_types
        self._start_rpc_listeners()
        kvs_trunk_driver.register()

    def _start_rpc_listeners(self):
        self.notifier = kvs_rpc.KvsAgentNotifyAPI(topics.AGENT)
        self.endpoints = [kvs_rpc.KvsServerRpcCallback(self.notifier)]
        self.topic = a_const.TOPIC_KNID
        self.conn = common_rpc.create_connection()
        self.conn.create_consumer(self.topic, self.endpoints, fanout=False)
        return self.conn.consume_in_threads()
