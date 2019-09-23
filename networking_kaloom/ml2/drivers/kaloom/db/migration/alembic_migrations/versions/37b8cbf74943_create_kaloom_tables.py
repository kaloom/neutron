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

"""Create kaloom tables

Revision ID: 37b8cbf74943
Revises: 
Create Date: 2018-09-05 11:38:49.919351

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '37b8cbf74943'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'kaloom_ml2_knid_mapping',
        sa.Column('kaloom_knid', sa.BigInteger(), nullable=False),
        sa.Column('network_id', sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint('kaloom_knid')
    )

    op.create_table(
        'kaloom_ml2_vlan_host_mapping',
        sa.Column('vlan_id', sa.Integer(), nullable=False),
        sa.Column('network_id', sa.String(length=255), nullable=False),
        sa.Column('host', sa.String(length=255), nullable=False),
        sa.Column('segment_id', sa.String(length=255), nullable=False),
        sa.Column('network_name', sa.String(length=255), nullable=False),
        sa.Column('state', sa.Enum('CREATING', 'CREATED', 'DELETING'), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('network_id', 'host')
    )

    
    op.create_table(
        'kaloom_ml2_vlan_reservation',
        sa.Column('host', sa.String(length=255), nullable=False),
        sa.Column('vlan_id', sa.Integer(), nullable=False),
        sa.Column('network_id', sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint('host', 'vlan_id')
    )

    op.create_table(
        'kaloom_ml2_tp_operation',
        sa.Column('network_id', sa.String(length=255), nullable=False),
        sa.Column('host', sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint('network_id', 'host')
    )