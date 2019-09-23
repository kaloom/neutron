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

"""Create kaloom_x_s_lock table

Revision ID: 37b8cbf74944
Revises: 37b8cbf74943
Create Date: 2019-08-22 12:11:49.919351

"""
from alembic import op
import sqlalchemy as sa
from networking_kaloom.ml2.drivers.kaloom.common import constants as kconst

# revision identifiers, used by Alembic.
revision = '37b8cbf74944'
down_revision = '37b8cbf74943'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'kaloom_x_s_lock',
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint('name')
    )
    op.execute(
        "insert into kaloom_x_s_lock(name) values('" + kconst.L3_LOCK_NAME + "')"
    )