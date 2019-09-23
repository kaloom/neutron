FROM registry.access.redhat.com/rhosp13/openstack-neutron-server
MAINTAINER Kaloom Inc. <openstack@kaloom.com>
LABEL name="rhosp13/openstack-neutron-server-kaloom-plugin" maintainer="openstack@kaloom.com" vendor="Kaloom" version="0.1" release="0" \
      summary="Red Hat OpenStack Platform 13.0 neutron-server Kaloom Plugin" \
      description="Red Hat OpenStack Platform 13.0 neutron-server Kaloom Plugin"

# switch to root and patch.
USER root
ENV RPM_VERSION RPM_VERSION_VALUE
ENV RPM_URL SERVER_URL/REPO_PATH/networking_kaloom-$RPM_VERSION-1.noarch.rpm
ENV RPM_SERVER_USER USER_VALUE
ENV RPM_SERVER_PASS PASS_VALUE
RUN curl https://dl.fedoraproject.org/pub/epel/epel-release-latest-7.noarch.rpm >/tmp/epel-release-latest-7.noarch.rpm \
    && rpm -ivh /tmp/epel-release-latest-7.noarch.rpm \
    && rm -f /tmp/epel-release-latest-7.noarch.rpm \
    && curl -L -u $RPM_SERVER_USER:$RPM_SERVER_PASS $RPM_URL > /tmp/networking_kaloom-$RPM_VERSION-1.noarch.rpm \
    && yum localinstall -y /tmp/networking_kaloom-*.noarch.rpm \
    && yum clean all \
    && rm -f /tmp/networking_kaloom-$RPM_VERSION-1.noarch.rpm \
    && echo -e "[KALOOM]\n# Kaloom VFabric controller IP\nkaloom_host=\n# Kaloom VFabric controller netconf port\nkaloom_port=\n# Kaloom VFabric controller username\nkaloom_username=\n# Kaloom private-key file to authenticate to VFabric Controller\nkaloom_private_key_file =\n##Kaloom password to authenticate to VFabric controller (as fallback)\nkaloom_password=\n##\n##For L3 Service plugin\n# Sync interval in seconds between L3 Service plugin and Kaloom vFabric.\n# If not set, a value of 180 seconds is assumed. (integer value)\nl3_sync_interval = 36000\n# Toggle to enable cleanup of routers by the sync worker.\n#If not set, a value of "False" is assumed. (boolean value: true, False)\nenable_cleanup = False\n" >> /etc/neutron/plugins/ml2/ml2_conf.ini

#Add required license as text file
RUN mkdir /licenses
COPY licensing.txt /licenses

# switch the container back to the default user
USER neutron
