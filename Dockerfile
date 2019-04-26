FROM registry.access.redhat.com/rhosp13/openstack-neutron-server
MAINTAINER Kaloom Inc. <openstack@kaloom.com>
LABEL name="rhosp13/openstack-neutron-server-kaloom-plugin" maintainer="openstack@kaloom.com" vendor="Kaloom" version="0.1" release="0" \
      summary="Red Hat OpenStack Platform 13.0 neutron-server Kaloom Plugin" \
      description="Red Hat OpenStack Platform 13.0 neutron-server Kaloom Plugin"

ENV PBR_VERSION=0.1.0

# switch to root and patch.
USER root
ADD . /opt/kaloom
RUN curl https://dl.fedoraproject.org/pub/epel/epel-release-latest-7.noarch.rpm -o /tmp/epel-release-latest-7.noarch.rpm \
  && rpm -ivh /tmp/epel-release-latest-7.noarch.rpm \
  && rm -f /tmp/epel-release-latest-7.noarch.rpm \
  && yum install -y python2-bitarray \
  && yum clean all \
  && cd /opt/kaloom; python setup.py install \
  && echo -e "[KALOOM]\n# Kaloom VFabric controller IP\nkaloom_host=\n# Kaloom VFabric controller netconf port\nkaloom_port=\n# Kaloom VFabric controller username\nkaloom_username=\n# Kaloom private-key file to authenticate to VFabric Controller\nkaloom_private_key_file =\n##Kaloom password to authenticate to VFabric controller (as fallback)\nkaloom_password=\n##\n##For L3 Service plugin\n# Sync interval in seconds between L3 Service plugin and Kaloom vFabric.\n# If not set, a value of 180 seconds is assumed. (integer value)\nl3_sync_interval = 36000\n# Toggle to enable cleanup of routers by the sync worker.\n#If not set, a value of "False" is assumed. (boolean value: true, False)\nenable_cleanup = False\n" >> /etc/neutron/plugins/ml2/ml2_conf.ini

#Add required license as text file
RUN mkdir /licenses
COPY LICENSE /licenses

# switch the container back to the default user
USER neutron
