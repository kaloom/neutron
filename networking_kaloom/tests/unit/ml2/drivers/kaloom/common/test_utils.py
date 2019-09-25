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

from neutron.tests import base
from networking_kaloom.ml2.drivers.kaloom.common import utils

class UtilsTestCase(base.BaseTestCase):
    def setUp(self):
        super(UtilsTestCase, self).setUp()

    def tearDown(self):
        super(UtilsTestCase, self).tearDown()

    def test_get_overlapped_subnet(self):
        given_ip_cidr = '192.168.0.1/24'
        existing_ip_cidrs = ['192.168.0.1/24', '192.168.0.2/24', '192.168.0.2/30', '192.168.1.1/22', '192.168.1.1/24']
        expected_overlapped = ['192.168.0.1/24', '192.168.0.2/24', '192.168.0.2/30', '192.168.1.1/22']
        overlapped_subnet_ip_cidrs = utils.get_overlapped_subnet(given_ip_cidr, existing_ip_cidrs )
        self.assertEquals(set(overlapped_subnet_ip_cidrs), set(expected_overlapped),
                          "result should be {}, got {}".format(expected_overlapped, overlapped_subnet_ip_cidrs))

        given_ip_cidr = '192.168.0.1/24'
        existing_ip_cidrs = ['192.168.1.1/24']
        expected_overlapped = []
        overlapped_subnet_ip_cidrs = utils.get_overlapped_subnet(given_ip_cidr, existing_ip_cidrs )
        self.assertEquals(set(overlapped_subnet_ip_cidrs), set(expected_overlapped),
                          "result should be {}, got {}".format(expected_overlapped, overlapped_subnet_ip_cidrs))
