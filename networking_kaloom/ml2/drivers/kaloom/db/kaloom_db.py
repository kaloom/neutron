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

import neutron.db.api as db_api
from oslo_log import log
from networking_kaloom.ml2.drivers.kaloom.db import kaloom_models
from neutron.db.models.segment import NetworkSegment
from neutron.db.models_v2 import Port
from neutron.plugins.ml2.models import PortBinding
import sqlalchemy.orm.exc as sa_exc

LOG = log.getLogger(__name__)


def create_knid_mapping(kaloom_knid, network_id, network_name):
    db_session = db_api.get_writer_session()
    mapping = kaloom_models.KaloomKnidMapping(kaloom_knid=kaloom_knid,
                                              network_id=network_id,
                                              network_name=network_name)

    db_session.add(mapping)
    db_session.flush()
    return mapping

def update_knid_mapping(network_id, stale):
    db_session = db_api.get_writer_session()
    try:
       mapping = db_session.query(kaloom_models.KaloomKnidMapping). \
                 filter_by(network_id=network_id).one()
       if mapping and mapping.stale != stale:
          mapping.stale = stale 
          db_session.flush()
    except sa_exc.NoResultFound:
        #nothing to update
        return None
    return True

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


def get_segment_id_for_network(network_id):
    db_session = db_api.get_reader_session()
    try:
        segment = db_session.query(NetworkSegment).filter_by(network_id=network_id,
                                                             segment_index=0).one()
        return segment.id
    except sa_exc.NoResultFound:
        return None

def delete_knid_mapping(network_id):
    db_session = db_api.get_writer_session()
    try:
        mapping = db_session.query(kaloom_models.KaloomKnidMapping). \
            filter_by(network_id=network_id).one()
        db_session.delete(mapping)
        db_session.flush()
    except:
        # no record was found, do nothing
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
    except sa_exc.NoResultFound:
        # no record was found, do nothing
        pass

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

def update_network_host_vlan_mapping(network_id, host, stale):
    db_session = db_api.get_writer_session()
    try:
        mapping = db_session.query(kaloom_models.KaloomVlanHostMapping). \
              filter_by(host=host, network_id=network_id).one()
        if mapping:
            mapping.stale = stale
            db_session.flush()
    except sa_exc.NoResultFound:
        return None
    return mapping

def get_vlan_mapping_for_network_and_host(network_id, host):
    db_session = db_api.get_reader_session()
    try:
        return db_session.query(kaloom_models.KaloomVlanHostMapping). \
            filter_by(host=host, network_id=network_id).one()
    except sa_exc.NoResultFound:
        return None

def delete_host_vlan_mapping(host, network_id):
    db_session = db_api.get_writer_session()
    try:
        mapping = db_session.query(kaloom_models.KaloomVlanHostMapping). \
            filter_by(host=host, network_id=network_id).one()
        db_session.delete(mapping)
        db_session.flush()
    except:
        # no record was found, do nothing
        pass

def get_all_vlan_mappings_for_host(host):
    db_session = db_api.get_reader_session()
    return db_session.query(kaloom_models.KaloomVlanHostMapping).filter_by(
        host=host).all()

def get_all_vlan_mappings_for_network(network_id):
    db_session = db_api.get_reader_session()
    return db_session.query(kaloom_models.KaloomVlanHostMapping).filter_by(
        network_id=network_id).all()


def get_ports_for_network_and_host(network_id, host):
    db_session = db_api.get_reader_session()
    network_host_ports = list()
    ports = db_session.query(Port).filter_by(network_id=network_id).all()
    for port in ports:
        binding = db_session.query(PortBinding).filter_by(port_id=port.id).one()
        if binding.host == host:
            network_host_ports.append(port)
    return network_host_ports


def get_mac_for_port(port_id):
    db_session = db_api.get_reader_session()
    try:
        port = db_session.query(Port).filter_by(id=port_id).one()
        return port.mac_address
    except sa_exc.NoResultFound:
        return None
