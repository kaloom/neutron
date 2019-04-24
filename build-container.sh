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

# Usage:  build-container.sh [<DOCKER_REGISTRY>]

DOCKER_REPO=$1

if [[ -z ${DOCKER_REPO} ]]; then
    DOCKER_REPO="registry.access.redhat.com"
fi 

NEUTRON_DOCKER="Dockerfile"
NEUTRON_KALOOM_VERSION=$(cat $NEUTRON_DOCKER | grep LABEL | grep -o -P '(?<=version=).*(?=release)' | tr -d '"' | tr -d ' '| tr -d '\')
NEUTRON_KALOOM_RELEASE=$(cat $NEUTRON_DOCKER | grep LABEL| grep -o -P '(?<=release=).*(?=)' | tr -d '"'| tr -d '\')

echo "Building container ${DOCKER_REPO}rhosp13/openstack-neutron-server-kaloom-plugin:${NEUTRON_KALOOM_VERSION}.${NEUTRON_KALOOM_RELEASE}"
docker build . -t ${DOCKER_REPO}/rhosp13/openstack-neutron-server-kaloom-plugin:${NEUTRON_KALOOM_VERSION}.${NEUTRON_KALOOM_RELEASE}