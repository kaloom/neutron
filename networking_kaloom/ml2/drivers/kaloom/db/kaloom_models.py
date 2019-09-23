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

import sqlalchemy as sa
from datetime import datetime
from neutron_lib.db import model_base
from oslo_log import log

LOG = log.getLogger(__name__)


class KaloomKnidMapping(model_base.BASEV2):
    __tablename__ = "kaloom_ml2_knid_mapping"

    kaloom_knid = sa.Column('kaloom_knid', sa.BigInteger(), primary_key=True)
    network_id = sa.Column('network_id', sa.String(length=255),
                           sa.ForeignKey('networks.id'), nullable=False)
    def __repr__(self):
        return "<KNID Mapping KIND:%s Network ID:%s>" % (self.kaloom_knid, self.network_id)


class KaloomVlanHostMapping(model_base.BASEV2):
    #CREATING: create_port_precommit tags 'CREATING' on first port 
    #CREATING -> CREATED: successful bind_port tags 'CREATED'.
    #CREATING -> DELETING: unsucessful bind_port calls delete_port that tags 'DELETING'
    #CREATING/CREATED -> DELETING: delete_port_precommit's tag for last port
    #DELETING->DELETED: delete_port_postcommit's tag, finished deletion (implicit: with row deletion) 
    __tablename__ = "kaloom_ml2_vlan_host_mapping"

    vlan_id = sa.Column('vlan_id', sa.Integer(), nullable=False)
    network_id = sa.Column('network_id', sa.String(length=255),
                           sa.ForeignKey('networks.id'),
                           primary_key=True, nullable=False)
    host = sa.Column('host', sa.String(length=255),
                     primary_key=True, nullable=False)
    segment_id = sa.Column('segment_id', sa.String(length=255), nullable=False)
    network_name = sa.Column('network_name', sa.String(length=255), nullable=False)
    state = sa.Column('state', sa.Enum('CREATING', 'CREATED', 'DELETING'), default='CREATING', nullable=False)
    timestamp = sa.Column('timestamp', sa.DateTime(), default=datetime.utcnow, nullable=False)
    sa.PrimaryKeyConstraint('network_id', 'host')

    def __repr__(self):
        return "<VLAN MAPPING host:network=(%s:%s) => vlan=%s>" % (self.host, self.network_id, self.vlan_id)

class KaloomVlanReservation(model_base.BASEV2):
    # Multiple controllers race for vlan allocation by writing (host,vlan_id) and whoever gets key violation is looser,
    # and retries for next vlan allocation.
    __tablename__ = "kaloom_ml2_vlan_reservation"

    network_id = sa.Column('network_id', sa.String(length=255),
                           sa.ForeignKey('networks.id'), nullable=False)
    host = sa.Column('host', sa.String(length=255),
                     primary_key=True, nullable=False)
    vlan_id = sa.Column('vlan_id', sa.Integer(), primary_key=True, nullable=False)
    sa.PrimaryKeyConstraint('host','vlan_id')

    def __repr__(self):
        return "<NETWORK MAPPING host:vlan_id=(%s:%s) => network_id=%s>" % (self.host, self.vlan_id, self.network_id)

class KaloomTPOperation(model_base.BASEV2):
    __tablename__ = "kaloom_ml2_tp_operation"

    network_id = sa.Column('network_id', sa.String(length=255),
                           sa.ForeignKey('networks.id'),
                           primary_key=True, nullable=False)
    host = sa.Column('host', sa.String(length=255),
                     primary_key=True, nullable=False)
    sa.PrimaryKeyConstraint('network_id', 'host')

    def __repr__(self):
        return "<TP Operation host:network=(%s:%s)>" % (self.host, self.network_id)

class KaloomConcurrency(model_base.BASEV2):
    __tablename__ = "kaloom_x_s_lock"

    name = sa.Column('name', sa.String(length=255),
                           primary_key=True, nullable=False)
    sa.PrimaryKeyConstraint('name')

    def __repr__(self):
        return "<name=(%s)>" % (self.name)
