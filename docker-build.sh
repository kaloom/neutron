#!/bin/bash
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

# wrapper script to build neutron plugin in build container

# source for kaloom/docs-neutron https://github.com/kaloom/docs-neutron
# source for kaloom/build-neutron https://github.com/kaloom/build-neutron

docker run --rm -u $(id -u ${USER}):$(id -g ${USER}) -v `pwd`:/opt/neutron -w /opt/neutron/docs kaloom/docs-neutron:1.0.0 make clean html htmlhelp latexpdf man linkcheck
docker run --rm -u $(id -u ${USER}):$(id -g ${USER}) -v `pwd`:/opt/neutron kaloom/build-neutron:2.0.0
