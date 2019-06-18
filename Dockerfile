FROM registry.access.redhat.com/rhosp13/openstack-neutron-server
MAINTAINER Kaloom Inc. <openstack@kaloom.com>
LABEL name="rhosp13/openstack-neutron-server-kaloom-plugin" maintainer="openstack@kaloom.com" vendor="Kaloom" version="0.1" release="1" \
      summary="Red Hat OpenStack Platform 13.0 neutron-server Kaloom Plugin" \
      description="Red Hat OpenStack Platform 13.0 neutron-server Kaloom Plugin"

ENV PBR_VERSION=0.1.1

# switch to root and patch.
USER root
ADD . /opt/kaloom
RUN  cd /opt/kaloom; python setup.py install
RUN  echo -e "[KALOOM]\n# Kaloom VFabric controller IP\nkaloom_host=\n# Kaloom VFabric controller netconf port\nkaloom_port=\n# Kaloom VFabric controller username\nkaloom_username=\n# Kaloom private-key file to authenticate to VFabric Controller\nkaloom_private_key_file =\n##Kaloom password to authenticate to VFabric controller (as fallback)\nkaloom_password=\n##\n##For L3 Service plugin\n# Sync interval in seconds between L3 Service plugin and Kaloom vFabric.\n# If not set, a value of 180 seconds is assumed. (integer value)\nl3_sync_interval = 36000\n" >> /etc/neutron/plugins/ml2/ml2_conf.ini

#Add required license as text file
RUN mkdir /licenses
COPY LICENSE /licenses

# switch the container back to the default user
USER neutron
