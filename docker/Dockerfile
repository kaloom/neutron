##
#
# Author  preetham.
#
# Redfig ansible_python  emulator image.
#
# Tag it as "kaloom/basebuilder:latest" upon building with the following:
# docker build  -f Dockerfile --tag kaloom/basebuilder:latest .
#
##
#

FROM centos:7
LABEL MAINTAINER="DevOps Redfig Australia <devops@redfig.com.au>"
RUN yum install -y epel-release && \ 
    yum install python python-pip git vim rpm-build ack -y &&\
    yum groupinstall 'Development Tools' -y &&\
    pip install --upgrade pip &&\
    pip install wheel setuptools &&\
    python -m pip install grpcio &&\
    python -m pip install grpcio-tools &&\
    pip install nose pbr mock oslo_utils &&\
    yum clean all && \
    rm -rf /var/cache/yum 
    