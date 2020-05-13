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

set -euo pipefail

BUILD_VERSION=""


usage() {
    echo "Build neutron ml2 plugin RPMs

USAGE
    $0 [-v|--version <version>] [-h|--help]

OPTIONS
$(show_options)
" >&2
    exit 1
}

show_options() {
    echo "\
    -v|--version <version>  Specify build version
    -h|--help               Shows usage of this build script" 
}

parse_args() {
    if [[ "$#" -eq 0 ]]; then
        build_rpm=1
    else
        while [[ "$#" -gt 0 ]]; do
            case $1 in
                -v|--version)
                    BUILD_VERSION=$2
                    shift 2
                    ;;
                -h|--help)
                    usage
                    ;;
                *)
                    echo "Unknown argument '$1'. Run '$0 --help' for help."
                    exit 1
                    ;;
            esac
        done
    fi
}

networking_kaloom_rpms() {
    BUILD_PATH="${HOME_PATH}"/build/networking_kaloom
    mkdir -p "${BUILD_PATH}"
 
    #Copy cfg file that includes README.md if building doc is required
    cp -vf networking_kaloom-setup.cfg "${BUILD_PATH}"/setup.cfg
    
    #compile and test
    python -m compileall ./

    #copy folders
    mkdir -p "${BUILD_PATH}"/networking_kaloom
    cp -vRT "${HOME_PATH}"/networking_kaloom/ "${BUILD_PATH}"/networking_kaloom/

    #copy files
    cp -v "${HOME_PATH}"/LICENSE "${BUILD_PATH}"/
    # cp -v "${HOME_PATH}"/build/docs/latex/ML2.pdf "${BUILD_PATH}"/
    cp -v "${HOME_PATH}"/setup.py "${BUILD_PATH}"/
    cp -v "${HOME_PATH}"/rpm-install.sh "${BUILD_PATH}"/

    #Build RPM
    cd ${BUILD_PATH}
    export PBR_VERSION=${BUILD_VERSION}
    python setup.py bdist_rpm --install-script=rpm-install.sh
    chmod -R 777 *
}

kaloom_kvs_agent_rpms() {
    BUILD_PATH="${HOME_PATH}"/build/kaloom_kvs_agent
    STUB_PATH="${BUILD_PATH}"/kaloom_kvs_agent/stub
    mkdir -p "${BUILD_PATH}"
    cd ${HOME_PATH}
    cp -f kaloom_kvs_agent-setup.cfg ${BUILD_PATH}/setup.cfg
    
    #compile and test
    python -m compileall ./

    #copy folders
    mkdir -p "${BUILD_PATH}"/kaloom_kvs_agent
    cp -vRT "${HOME_PATH}"/kaloom_kvs_agent/ "${BUILD_PATH}"/kaloom_kvs_agent/
    mkdir -p "${BUILD_PATH}"/vif_plug_kaloom_kvs
    cp -vRT "${HOME_PATH}"/vif_plug_kaloom_kvs/ "${BUILD_PATH}"/vif_plug_kaloom_kvs/
    mkdir -p "${BUILD_PATH}"/nova
    cp -vRT "${HOME_PATH}"/nova/ "${BUILD_PATH}"/nova/
    cp -vR "${HOME_PATH}"/etc/ "${BUILD_PATH}"/

    # Build
    mkdir -p "${STUB_PATH}"
    cd "${HOME_PATH}"/protobuf
    python -m grpc_tools.protoc -I. --python_out="${STUB_PATH}" \
        kvs_msg.proto
    python -m grpc_tools.protoc -I. --python_out="${STUB_PATH}" \
        ports.proto
    python -m grpc_tools.protoc -I. --python_out="${STUB_PATH}" \
        error.proto
    python -m grpc_tools.protoc -I. --python_out="${STUB_PATH}" \
        --grpc_python_out="${STUB_PATH}" service.proto
    touch ${STUB_PATH}/__init__.py

    #copy files
    cp -v "${HOME_PATH}"/LICENSE "${BUILD_PATH}"/
    # cp -v "${HOME_PATH}"/build/docs/latex/ML2.pdf "${BUILD_PATH}"/
    cp -v "${HOME_PATH}"/setup.py "${BUILD_PATH}"/
    cp -v "${HOME_PATH}"/rpm-install.sh "${BUILD_PATH}"/
    cp -v "${HOME_PATH}"/rpm-post-install.sh "${BUILD_PATH}"/

    #Build RPM
    cd ${BUILD_PATH}
    export PBR_VERSION=${BUILD_VERSION}
    python setup.py bdist_rpm --post-install=rpm-post-install.sh --install-script=rpm-install.sh
    chmod -R 777 *
}

run_networking_kaloom_test() {
    cd ${HOME_PATH}
    nosetests networking_kaloom/tests/
}

main() {
    readonly HOME_PATH="$(pwd)"
    networking_kaloom_rpms
    kaloom_kvs_agent_rpms
    #run_networking_kaloom_test
}

main "$@"