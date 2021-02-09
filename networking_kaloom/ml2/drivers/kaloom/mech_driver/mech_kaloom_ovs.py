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

from oslo_log import log
from oslo_config import cfg
from neutron_lib import constants
from neutron.plugins.ml2.drivers.openvswitch.mech_driver.mech_openvswitch import OpenvswitchMechanismDriver
from neutron.plugins.ml2.common import exceptions as ml2_exc
from neutron_lib.api.definitions import portbindings
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
from neutron_lib.db import api as db_api
from random import randint
from neutron_lib import rpc as common_rpc
from neutron_lib.agent import topics
from networking_kaloom.ml2.drivers.kaloom.mech_driver import kvs_rpc
from networking_kaloom.services.trunk import driver as kvs_trunk_driver
import random

LOG = log.getLogger(__name__)

kaloom_config.register_opts()


class KaloomOVSMechanismDriver(OpenvswitchMechanismDriver):
    """
    OVS mechanism driver for Kaloom. Extends the default
    OVS driver and then does a post commit operation to
    set the correct VNI
    """

    def __init__(self):
        LOG.info("KaloomOVSMechanismDriver __init__ called")
        self.segments_plugin = segments_plugin.Plugin.get_instance()
        self.vlan_pool = pool.KaloomVlanPool()
        self.kaloom = KaloomNetconf(cfg.CONF.KALOOM.kaloom_host,
                                    cfg.CONF.KALOOM.kaloom_port,
                                    cfg.CONF.KALOOM.kaloom_username,
                                    cfg.CONF.KALOOM.kaloom_private_key_file,
                                    cfg.CONF.KALOOM.kaloom_password)
        self._start_rpc_listeners()
        self.prefix = '__OpenStack__'
        super(KaloomOVSMechanismDriver, self).__init__()
        kvs_trunk_driver.register()

    def _start_rpc_listeners(self):
        self.notifier = kvs_rpc.KvsAgentNotifyAPI(topics.AGENT)
        self.endpoints = [kvs_rpc.KvsServerRpcCallback(self.notifier)]
        self.topic = a_const.TOPIC_KNID
        self.conn = common_rpc.Connection()
        self.conn.create_consumer(self.topic, self.endpoints, fanout=False)
        return self.conn.consume_in_threads()

    def get_kvs_vif_type(self, context, agent, segment):
        if (agent['configurations'].get('datapath_type') ==
                a_const.KVS_DATAPATH_NETDEV):
            return portbindings.VIF_TYPE_VHOST_USER
        return self.vif_type

    def get_kvs_vif_details(self, context, agent, segment):
        vif_details = self._pre_get_kvs_vif_details(agent, context)
        return vif_details

    def _pre_get_kvs_vif_details(self, agent, context):
        vif_type = self.get_kvs_vif_type(context, agent, segment=None)
        if vif_type != portbindings.VIF_TYPE_VHOST_USER:
            details = dict(self.vif_details)
        else:
            sock_path = self.kvs_agent_vhu_sockpath(agent, context.current['id'])
            mode = portbindings.VHOST_USER_MODE_CLIENT
            details = {portbindings.CAP_PORT_FILTER: False,
                       portbindings.VHOST_USER_OVS_PLUG: True,
                       portbindings.OVS_DATAPATH_TYPE: a_const.KVS_DATAPATH_SYSTEM,
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
        if agent['agent_type'] == a_const.AGENT_TYPE_KALOOM_KVS:
            return [kconst.TYPE_KNID]
        else:
            return (agent['configurations'].get('tunnel_types', []) +
                    [kconst.TYPE_KNID, constants.TYPE_FLAT,
                     constants.TYPE_VLAN])

    def bind_port(self, context):
        ovs_present = self._is_ovs_agent_present(context)
        kvs_present = self._is_kvs_agent_present(context)
        selection = []
        if ovs_present:
            selection.append("ovs")
        if kvs_present:
            selection.append("kvs")
        if len(selection):
            selected = random.choice(selection)
            if selected == "kvs":
                LOG.info("Using KVS specific logic")
                agent_type_temp = self.agent_type
                self.agent_type = a_const.AGENT_TYPE_KALOOM_KVS
                super(KaloomOVSMechanismDriver, self).bind_port(context)
                self.agent_type = agent_type_temp
            elif selected == "ovs":
                LOG.info("Using OVS specific logic")
                super(KaloomOVSMechanismDriver, self).bind_port(context)
        else:
            LOG.debug("Port %(pid)s on network %(network)s not bound, "
                      "no agent of type %(at1)s and %(at2)s are registered",
                      {'pid': context.current['id'],
                       'at1': a_const.AGENT_TYPE_KALOOM_KVS,
                       'at2': constants.AGENT_TYPE_OVS,
                       'network': context.network.current['id']})

    def try_to_bind_segment_for_agent(self, context, segment, agent):
        if self.check_segment_for_agent(segment, agent):
            if agent['agent_type'] == a_const.AGENT_TYPE_KALOOM_KVS:
                return self._try_to_bind_segment_kvs_agent(context, segment, agent)
            else:
                return self._try_to_bind_segment_ovs_agent(context, segment, agent)

        return False

    def _try_to_bind_segment_ovs_agent(self, context, segment, agent):
        network_id = segment.get('network_id')
        try:
            nw_name = utils._kaloom_nw_name(self.prefix, network_id, utils._get_network_name(network_id))
        except NetworkNotFound as e:
            LOG.error(e)
            return False
        host = context.current.get('binding:host_id')

        #lock concurrent attach/detach for vfabric TP 
        if not utils.tp_operation_lock(host, network_id):
            return False

        try:
          local_vlan_mapping = kaloom_db.get_vlan_mapping_for_network_and_host(network_id, host)
          if local_vlan_mapping:
              if local_vlan_mapping.stale:
                  LOG.info('stale vlan=%s mapping found on host=%s, network=%s, reusing the same', local_vlan_mapping.vlan_id, host, network_id)
                  kaloom_db.update_network_host_vlan_mapping(network_id=network_id, host=host, stale=False) #no more stale

          else: #in case of None
              try:
                  tp_id = self.kaloom.get_tp_by_annotation(host).get('id')
              except Exception as e:
                  msg = "Error on get_tp_by_annotation for host %s: %s" % (host, e)
                  raise ValueError(msg)
              attach_name = '%s:%s' % (network_id, tp_id)
              local_vlan_mapping = self._allocate_local_vlan_mapping(context, network_id, host, segment, nw_name)
              if local_vlan_mapping is None:
                  msg = 'Vlan could not be allocated.' 
                  raise ValueError(msg)

              local_vlan_id = local_vlan_mapping.vlan_id
              try:
                  self.kaloom.attach_tp_to_l2_network(nw_name, attach_name, tp_id, local_vlan_id)
              except Exception as e:
                  msg = "Error on attach_tp_to_l2_network for tpid %s vlan %s nw %s: %s" % (tp_id, local_vlan_id, nw_name, e)
                  # release vlan and segment that was just created.
                  self._remove_local_segment(context._plugin_context, local_vlan_mapping.segment_id)
                  self._remove_local_vlan_mapping(local_vlan_mapping)
                  raise ValueError(msg)

          local_vlan_id = local_vlan_mapping.vlan_id
          local_seg_id = local_vlan_mapping.segment_id
          context.set_binding(local_seg_id,
                              self.get_vif_type(context, agent, segment),
                              self.get_vif_details(context, agent, segment))
          LOG.info("BINDED SEGMENT VLAN %d host %s segment %s " % (local_vlan_id, host, local_seg_id))
          return True
        except Exception as e:
            LOG.error("Error during bind_port on host=%s, network=%s, err_msg:%s", host, network_id, e)
            return False
        finally:
            utils.tp_operation_unlock(host, network_id)  #release lock 

    def _allocate_local_vlan_mapping(self, context, network_id, host, segment, nw_name):
        local_vlan_id = self.vlan_pool.allocate_local_vlan(host, network_id)
        if local_vlan_id is None:
            return None
        local_seg = self._create_segment(context._plugin_context, segment.get('network_id'),
                                         segment.get('physical_network'), 'vlan',
                                         local_vlan_id, 1, context.host, False)
        try:
            kaloom_db.create_network_host_vlan_mapping(network_id, host, local_seg.get('id'), local_vlan_id, nw_name)
        except Exception as e:
            LOG.error("Error create_network_host_vlan_mapping VLAN=%d for host=%s, network=%s, err_msg: %s", local_vlan_id, host, network_id, e)
            #clear record on vlan reservation
            kaloom_db.delete_vlan_reservation(host=host, vlan_id=local_vlan_id)
            return None

        LOG.info("LOCAL VLAN NOT FOUND: ALLOCATING VLAN %d host, network (%s,%s)" %
                 (local_vlan_id, host, network_id))
        local_vlan_mapping = type('local_vlan_mapping', (object,), {'vlan_id' : local_vlan_id, 'segment_id': local_seg.get('id')})
        return local_vlan_mapping

    def _try_to_bind_segment_kvs_agent(self, context, segment, agent):
        network_id = segment.get('network_id')
        segment_id = kaloom_db.get_segment_id_for_network(network_id)
        vif_details = self.get_kvs_vif_details(context, agent, segment)
        vif_details['knid'] = kaloom_db.get_knid_for_network(network_id)

        context.set_binding(segment_id,
                            self.get_kvs_vif_type(context, agent, segment),
                            vif_details
                            )
        return True

    #"openstack network delete .." calls first delete_port* if any on the network, and then calls delete_network*
    #delete_port_postcommit: Runtime errors are not expected, and will not prevent the resource from being deleted.
    #so cleanup as much as possible.
    def delete_port_postcommit(self, context):
        super(KaloomOVSMechanismDriver, self).delete_port_postcommit(context)

        network_id = context.current.get('network_id')
        host = context.host

        #lock concurrent attach/detach for vfabric TP
        if not utils.tp_operation_lock(host, network_id):
            e = "tp_operation_lock failed on delete_port for host=%s, network_id=%s, do nothing." % (host, network_id)
            LOG.warning(e)
            #in case concurrent attach happening, we don't need to tp_detach, in case concurrent detach happening, that will take care of.
            return
        try:
          local_vlan_mapping = kaloom_db.get_vlan_mapping_for_network_and_host(network_id, host)

          # KVS case, we don't need to do anything
          if not local_vlan_mapping:
              return # applies after finally

          local_vlan_id = local_vlan_mapping.vlan_id
          if self._get_port_left_on_host_for_network(host, network_id) <= 0: #on port_postcommit, last port has been already deleted.
              tp_id = self.kaloom.get_tp_by_annotation(host).get('id')
              self.kaloom.detach_tp_from_l2_network(local_vlan_mapping.network_name, tp_id)
              #in case vfabric operation successful, release vlan and segment
              LOG.info("Last port on host:%s, removing vlan:%s network:%s mapping", host, local_vlan_id, network_id)
              self._remove_local_vlan_mapping(local_vlan_mapping)
              self._remove_local_segment(context._plugin_context, local_vlan_mapping.segment_id)
        except Exception as e:
            LOG.error("Tag stale for host=%s, network=%s as error caught during delete_port %s", host, network_id, e)
            kaloom_db.update_network_host_vlan_mapping(network_id=network_id, host=host, stale=True) #tag stale
        finally:
            utils.tp_operation_unlock(host, network_id)  #release lock

    #create_network_postcommit "rollbacks" on exception, by calling delete_network*, so extra care needed.
    def create_network_postcommit(self, context):
        super(KaloomOVSMechanismDriver, self).create_network_postcommit(context)

        network_id = context.current.get('id')
        nw_name = utils._kaloom_nw_name(self.prefix, network_id, context.current.get('name'))
        #force clean if vfabric network already exists, probably of unsuccessful delete_network_postcommit
        knid_mapping = kaloom_db.get_knid_mapping(network_id=network_id)
        if knid_mapping:
             try:
                self._clean_local_vlan_mappings(network_id)
                kaloom_db.delete_knid_mapping(network_id)
                self.kaloom.delete_l2_network(knid_mapping.network_name)
             except Exception as e:
                #forced clean: no error raise
                LOG.warning("create_network_postcommit: Error on clearing overlapping vfabric network=%s errors: %s", knid_mapping.network_name,  e)
        #create nw in vfabric
        try:
            knid = self.kaloom.create_l2_network(nw_name, kconst.DEFAULT_VLAN_ID).get('kaloom_knid')
        except Exception as e:
            LOG.error("errors: %s", e)
            #raising an exception will result in rollback of the transaction
            raise ml2_exc.MechanismDriverError(method = 'create_network_postcommit', errors = e)
        LOG.info("Created Kaloom network with KNID %d " % knid)
        kaloom_db.create_knid_mapping(kaloom_knid=knid,
                                      network_id=network_id,network_name=nw_name)

    #delete_network_postcommit called after db transaction: the caller ignores the error i.e won't undo the action by recreating the network.
    def delete_network_postcommit(self, context):
        super(KaloomOVSMechanismDriver, self).delete_network_postcommit(context)
        network_id = context.current.get('id')

        knid_mapping = kaloom_db.get_knid_mapping(network_id=network_id)
        if knid_mapping: #rollback on create_network_postcommit calls delete_network so the knid_mapping may not exist
           nw_name = knid_mapping.network_name
           try:
               self.kaloom.delete_l2_network(nw_name)
               kaloom_db.delete_knid_mapping(network_id)
               self._clean_local_vlan_mappings(network_id)
           except Exception as e:
               LOG.error("errors: %s", e)
               kaloom_db.update_knid_mapping(network_id=network_id, stale=True) #tag stale
        return

    def _get_port_left_on_host_for_network(self, host, network_id):
        ports = kaloom_db.get_ports_for_network_and_host(network_id, host)
        return len(ports)


    def _remove_local_vlan_mapping(self, local_vlan_mapping):
        if local_vlan_mapping:
            kaloom_db.delete_host_vlan_mapping(network_id=local_vlan_mapping.network_id, host=local_vlan_mapping.host)
            #clear record on vlan reservation
            kaloom_db.delete_vlan_reservation(host=local_vlan_mapping.host, vlan_id=local_vlan_mapping.vlan_id)

    def _clean_local_vlan_mappings(self, network_id):
        """ When a network is deleted, remove all residual mappings for Local VLAN """
        mappings = kaloom_db.get_all_vlan_mappings_for_network(network_id)
        for m in mappings:
            kaloom_db.delete_host_vlan_mapping(network_id=m.network_id,
                                               host=m.host)
        #clear record on vlan reservation 
        mappings = kaloom_db.get_all_vlan_reservations_for_network(network_id)
        for m in mappings:
            kaloom_db.delete_vlan_reservation(host=m.host, vlan_id=m.vlan_id)

    def _is_kvs_agent_present(self, context):
        agents_on_host = context.host_agents(a_const.AGENT_TYPE_KALOOM_KVS)
        LOG.info("Found %d agents of KVS type" % len(agents_on_host))
        if len(agents_on_host):
            return True
        return False

    def _is_ovs_agent_present(self, context):
        agents_on_host = context.host_agents(constants.AGENT_TYPE_OVS)
        LOG.info("Found %d agents of OVS type" % len(agents_on_host))
        if len(agents_on_host):
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

    def _remove_local_segment(self, context, segment_id):
        with db_api.context_manager.writer.using(context):
            netseg_obj = network_obj.NetworkSegment.get_object(context, id=segment_id)
            if netseg_obj:
               netseg_obj.delete()
