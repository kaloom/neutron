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

# Usage:  publish-containers.sh <ARTIFACTORY_REPO> <DOCKER_REGISTRY>

ARTIFACTORY_REPO=$1
DOCKER_REPO=$2

RPM_VERSION=$(ls build/dist/ | grep noarch | cut -d'-' -f2)
NEUTRON_DOCKER="docker/openstack-neutron-server-kaloom/Dockerfile"
NEUTRON_KALOOM_VERSION=$(cat $NEUTRON_DOCKER | grep LABEL | grep -o -P '(?<=version=).*(?=release)' | tr -d '"' | tr -d ' '| tr -d '\')
NEUTRON_KALOOM_RELEASE=$(cat $NEUTRON_DOCKER | grep LABEL| grep -o -P '(?<=release=).*(?=)' | tr -d '"'| tr -d '\')


echo "RPM version $RPM_VERSION to be installed on rhos container"

sed -i 's#RPM_VERSION_VALUE#'"$RPM_VERSION"'#g' $NEUTRON_DOCKER
sed -i 's#SERVER_URL#'"$ARTIFACTORY_URL"'#g' $NEUTRON_DOCKER
sed -i 's#REPO_PATH#'"$ARTIFACTORY_REPO_PATH"'#g' $NEUTRON_DOCKER
sed -i 's#USER_VALUE#'"$ARTIFACTORY_USER"'#g' $NEUTRON_DOCKER
sed -i 's#PASS_VALUE#'"$ARTIFACTORY_PASS"'#g' $NEUTRON_DOCKER


echo "Building container ${DOCKER_REPO}rhosp13/openstack-neutron-server-kaloom-plugin:${NEUTRON_KALOOM_VERSION}.${NEUTRON_KALOOM_RELEASE}"
docker build docker/openstack-neutron-server-kaloom/ -t ${DOCKER_REPO}rhosp13/openstack-neutron-server-kaloom-plugin:${NEUTRON_KALOOM_VERSION}.${NEUTRON_KALOOM_RELEASE}
echo "Pushing container ${DOCKER_REPO}rhosp13/openstack-neutron-server-kaloom-plugin:${NEUTRON_KALOOM_VERSION}.${NEUTRON_KALOOM_RELEASE}"
docker push ${DOCKER_REPO}rhosp13/openstack-neutron-server-kaloom-plugin:${NEUTRON_KALOOM_VERSION}.${NEUTRON_KALOOM_RELEASE}
