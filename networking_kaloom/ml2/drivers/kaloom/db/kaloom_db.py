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

import neutron_lib.db.api as db_api
from oslo_log import log
from neutron.db.models import l3
from networking_kaloom.ml2.drivers.kaloom.db import kaloom_models
from neutron.db.models.segment import NetworkSegment
from neutron.db.models_v2 import Port, Network
from neutron.plugins.ml2.models import PortBinding
import sqlalchemy.orm.exc as sa_exc
from sqlalchemy import or_, and_, func
from datetime import datetime, timedelta

LOG = log.getLogger(__name__)


def create_knid_mapping(kaloom_knid, network_id):
    db_session = db_api.get_writer_session()
    mapping = kaloom_models.KaloomKnidMapping(kaloom_knid=kaloom_knid,
                                              network_id=network_id)

    db_session.add(mapping)
    db_session.flush()
    return mapping

def get_knid_mapping(network_id):
    db_session = db_api.get_reader_session()
    try:
        return db_session.query(kaloom_models.KaloomKnidMapping). \
            filter_by(network_id=network_id).one()
    except sa_exc.NoResultFound:
        return None


def get_knid_for_network(network_id):
    db_session = db_api.get_reader_session()
    try:
        return db_session.query(kaloom_models.KaloomKnidMapping). \
            filter_by(network_id=network_id).one().kaloom_knid
    except sa_exc.NoResultFound:
        return None


def get_segmentation_id_for_network(network_id):
    db_session = db_api.get_reader_session()
    try:
        segment = db_session.query(NetworkSegment).filter_by(network_id=network_id,
                                                             segment_index=0).one()
        return segment.segmentation_id
    except sa_exc.NoResultFound:
        return None


def get_segment_for_network(network_id):
    db_session = db_api.get_reader_session()
    try:
        segment = db_session.query(NetworkSegment).filter_by(network_id=network_id,
                                                             segment_index=0).one()
        return segment
    except sa_exc.NoResultFound:
        return None

def delete_knid_mapping(network_id):
    db_session = db_api.get_writer_session()
    try:
        mapping = db_session.query(kaloom_models.KaloomKnidMapping). \
            filter_by(network_id=network_id).one()
        db_session.delete(mapping)
        db_session.flush()
    except (sa_exc.NoResultFound, sa_exc.StaleDataError):
        # no record was found, do nothing
        # ignore concurrent deletion
        pass

def get_all_knid_mappings():
    db_session = db_api.get_reader_session()
    return db_session.query(kaloom_models.KaloomKnidMapping).all()

def create_vlan_reservation(host, vlan_id, network_id):
    db_session = db_api.get_writer_session()
    mapping = kaloom_models.KaloomVlanReservation(host=host,
                                                  vlan_id=vlan_id,
                                                  network_id=network_id)
    db_session.add(mapping)
    db_session.flush()
    return mapping

def get_all_vlan_reservations_for_network(network_id):
    db_session = db_api.get_reader_session()
    return db_session.query(kaloom_models.KaloomVlanReservation).filter_by(
        network_id=network_id).all()

def delete_vlan_reservation(host, vlan_id):
    db_session = db_api.get_writer_session()
    try:
        mapping = db_session.query(kaloom_models.KaloomVlanReservation). \
            filter_by(host=host, vlan_id=vlan_id).one()
        db_session.delete(mapping)
        db_session.flush()
    except (sa_exc.NoResultFound, sa_exc.StaleDataError):
        # no record was found, do nothing
        # ignore concurrent deletion
        pass

def create_entry_for_Lock(name):
    db_session = db_api.get_writer_session()
    mapping = kaloom_models.KaloomConcurrency(name=name)
    db_session.add(mapping)
    db_session.flush()
    return mapping

def delete_entry_for_Lock(name):
    db_session = db_api.get_writer_session()
    try:
        mapping = db_session.query(kaloom_models.KaloomConcurrency). \
            filter_by(name=name).one()
        db_session.delete(mapping)
        db_session.flush()
    except (sa_exc.NoResultFound, sa_exc.StaleDataError):
        # no record was found, do nothing
        # ignore concurrent deletion
        pass

#this runs in the context of caller's transaction
#Locks (x/write or s/shared) are applied by a TX (transaction) to data,
#which may block other TXs from accessing the same data during the TX's life.
def get_Lock(db_session, name, read, caller_msg):
    try:
        db_session.query(kaloom_models.KaloomConcurrency). \
            filter_by(name=name). \
            with_for_update(read=read, nowait=False).one()
    except Exception as e:
        msg = "get_Lock read:%s on name:%s for %s , error: %s" % ( read, name, caller_msg, e)
        raise ValueError(msg)

def create_tp_operation(host, network_id):
    db_session = db_api.get_writer_session()
    mapping = kaloom_models.KaloomTPOperation(host=host,
                                              network_id=network_id)

    db_session.add(mapping)
    db_session.flush()
    return mapping

def delete_tp_operation(host, network_id):
    db_session = db_api.get_writer_session()
    try:
        mapping = db_session.query(kaloom_models.KaloomTPOperation). \
            filter_by(host=host, network_id=network_id).one()
        db_session.delete(mapping)
        db_session.flush()
    except (sa_exc.NoResultFound, sa_exc.StaleDataError):
        # no record was found, do nothing
        # ignore concurrent deletion
        pass
    except Exception as e:
        LOG.error('error while trying to delete_tp_operation on host=%s, network_id=%s, errmsg:%s', host, network_id, e)
        pass

def get_all_vlan_mappings_for_host(host):
    db_session = db_api.get_reader_session()
    return db_session.query(kaloom_models.KaloomVlanHostMapping).filter_by(
        host=host).all()

def create_network_host_vlan_mapping(network_id, host, segment_id, vlan_id, network_name):
    db_session = db_api.get_writer_session()
    mapping = kaloom_models.KaloomVlanHostMapping(host=host,
                                                  network_id=network_id,
                                                  segment_id=segment_id,
                                                  vlan_id=vlan_id,
                                                  network_name=network_name)

    db_session.add(mapping)
    db_session.flush()
    return mapping

def update_state_on_network_host_vlan_mapping(network_id, host, state):
    db_session = db_api.get_writer_session()
    try:
        mapping = db_session.query(kaloom_models.KaloomVlanHostMapping). \
              filter_by(host=host, network_id=network_id).one()
        if mapping and mapping.state != state:
            mapping.state = state
            mapping.timestamp = datetime.utcnow()
            db_session.flush()
    except (sa_exc.NoResultFound, sa_exc.StaleDataError):
        #nothing to update
        #concurrent deletion happened.
        return False
    return True

def get_vlan_mapping_for_network_and_host(network_id, host):
    db_session = db_api.get_reader_session()
    try:
        return db_session.query(kaloom_models.KaloomVlanHostMapping). \
            filter_by(host=host, network_id=network_id).one()
    except sa_exc.NoResultFound:
        return None

def get_stale_vlan_mappings(creating_seconds, deleting_seconds):
    db_session = db_api.get_reader_session()
    try:
        now = datetime.utcnow()
        old_creating_date = now - timedelta(seconds = creating_seconds)
        old_deleting_date = now - timedelta(seconds = deleting_seconds)
        return db_session.query(kaloom_models.KaloomVlanHostMapping). \
            filter(or_(and_(kaloom_models.KaloomVlanHostMapping.state == "CREATING", \
                        kaloom_models.KaloomVlanHostMapping.timestamp <= old_creating_date),\
                       and_(kaloom_models.KaloomVlanHostMapping.state == "DELETING", \
                        kaloom_models.KaloomVlanHostMapping.timestamp <= old_deleting_date)
                      )).all()
    except sa_exc.NoResultFound:
        return None

def delete_host_vlan_mapping(host, network_id):
    db_session = db_api.get_writer_session()
    try:
        mapping = db_session.query(kaloom_models.KaloomVlanHostMapping). \
            filter_by(host=host, network_id=network_id).one()
        db_session.delete(mapping)
        db_session.flush()
    except (sa_exc.NoResultFound, sa_exc.StaleDataError):
        # no record was found, do nothing
        # ignore concurrent deletion
        pass

def get_all_vlan_mappings_for_host(host):
    db_session = db_api.get_reader_session()
    return db_session.query(kaloom_models.KaloomVlanHostMapping).filter_by(
        host=host).all()

def get_all_vlan_mappings_for_network(network_id):
    db_session = db_api.get_reader_session()
    return db_session.query(kaloom_models.KaloomVlanHostMapping).filter_by(
        network_id=network_id).all()


def get_port_count_for_network_and_host(network_id, host):
    db_session = db_api.get_reader_session()
    return db_session.query(func.count(Port.id)).join(PortBinding).filter(Port.network_id==network_id, PortBinding.host == host).scalar()

def get_mac_for_port(port_id):
    db_session = db_api.get_reader_session()
    try:
        port = db_session.query(Port).filter_by(id=port_id).one()
        return port.mac_address
    except sa_exc.NoResultFound:
        return None

def get_networks():
    db_session = db_api.get_reader_session()
    try:
        networks = db_session.query(Network.id, Network.name).all()
        return networks
    except sa_exc.NoResultFound:
        return []

