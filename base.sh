#!/bin/bash

BASEDIR_MASTER=${BASEDIR:="$( cd "$(dirname "$0")" ; pwd -P )"}

if docker info &> /dev/null ; then 
    echo"[ERROR] docker not installed."
    exit 128
fi 

#Build base image.
(
    cd ${BASEDIR_MASTER} &&\
    docker build  -f Dockerfile --tag kaloom/basebuilder:latest .
)

docker run -u $(id -u ${USER}):$(id -g ${USER}) \
--rm -v ${BASEDIR_MASTER}:/data \
-w /data kaloom/basebuilder:latest \
bash -c " bash -x build.sh"