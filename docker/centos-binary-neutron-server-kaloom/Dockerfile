FROM tripleoqueens/centos-binary-neutron-server:current-tripleo
MAINTAINER Kaloom Inc. <rdo@kaloom.com>

ARG VCS_REF
ARG BUILD_DATE
ARG KALOOM_VERSION
ARG KALOOM_RELEASE

LABEL name="tripleoqueens/centos-binary-neutron-server-kaloom-plugin" maintainer="rdo@kaloom.com" vendor="Kaloom" \
      summary="RDO Centos neutron-server Kaloom Plugin" \
      description="RDO Centos neutron-server Kaloom Plugin" \
      authoritative-source-url="" \
      batch="" \
      com.redhat.build-host="" \
      vcs-ref="" \
      build-date=""
LABEL org.label-schema.vcs-ref=$VCS_REF
LABEL org.label-schema.build-date=$BUILD_DATE
LABEL version=$KALOOM_VERSION
LABEL release=$KALOOM_RELEASE

# switch to root and patch.
USER root
ADD networking_kaloom-*.noarch.rpm /tmp/
RUN yum localinstall -y /tmp/networking_kaloom-*.noarch.rpm \
    && rm -f /tmp/networking_kaloom-*.noarch.rpm \
    && echo -e "[KALOOM]\n# Kaloom VFabric controller IP\nkaloom_host=\n# Kaloom VFabric controller netconf port\nkaloom_port=\n# Kaloom VFabric controller username\nkaloom_username=\n# Kaloom private-key file to authenticate to VFabric Controller\nkaloom_private_key_file =\n##Kaloom password to authenticate to VFabric controller (as fallback)\nkaloom_password=\n##\n##For L3 Service plugin\n# Sync interval in seconds between L3 Service plugin and Kaloom vFabric.\n# If not set, a value of 180 seconds is assumed. (integer value)\nl3_sync_interval = 36000\n" >> /etc/neutron/plugins/ml2/ml2_conf.ini

#Add required license as text file
RUN mkdir /licenses
COPY licensing.txt /licenses

# switch the container back to the default user
USER neutron
