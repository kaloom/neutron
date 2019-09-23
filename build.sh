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

build_rpm=0
build_doc=0
BUILD_VERSION=""


usage() {
    echo "Build neutron ml2 plugin

USAGE
    $0 [-a|--all] [-r|--rpm] [-v|--version <version>] [-h|--help]

OPTIONS
$(show_options)
" >&2
    exit 1
}

show_options() {
    echo "\
    -a|--all                Builds rpm and doc artifacts inside containers
    -r|--rpm                Builds rpms inside container
    -v|--version <version>  Specify build version
    -h|--help               Shows usage of this build script" 
}

parse_args() {
    if [[ "$#" -eq 0 ]]; then
        build_rpm=1
    else
        while [[ "$#" -gt 0 ]]; do
            case $1 in
                -a|--all)
                    build_rpm=1
                    build_doc=1
                    shift
                    ;;
                -r|--rpm)
                    build_rpm=1
                    shift
                    ;;
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

main() {
  
    readonly HOME_PATH="$(pwd)"
    readonly BUILD_PATH="${HOME_PATH}"/build
    
    parse_args "$@"

    #Copy cfg file that includes README.pdf if building doc is required
    if [[ ${build_doc} -eq 0 ]]; then
        cp -f setup.cfg.nodoc setup.cfg
    else
        cp -f setup.cfg.doc setup.cfg
    fi
    
    #compile and test
    python -m compileall ./

    #copy folders
    mkdir -p "${BUILD_PATH}"/networking_kaloom
    cp -vRT "${HOME_PATH}"/networking_kaloom/ "${BUILD_PATH}"/networking_kaloom/

    #copy files
    cp -v "${HOME_PATH}"/LICENSE "${BUILD_PATH}"/
    cp -v "${HOME_PATH}"/README.md "${BUILD_PATH}"/
    if [[ ${build_doc} -eq 1 ]]; then
        cp -v "${HOME_PATH}"/README.pdf "${BUILD_PATH}"/
    fi
    cp -v "${HOME_PATH}"/setup.cfg "${BUILD_PATH}"/
    cp -v "${HOME_PATH}"/setup.py "${BUILD_PATH}"/
    cp -v "${HOME_PATH}"/kaloom_logo.jpg "${BUILD_PATH}"/
    cp -v "${HOME_PATH}"/rpm-install.sh "${BUILD_PATH}"/

    #Build RPM
    cd ${BUILD_PATH}
    export PBR_VERSION=${BUILD_VERSION}
    python setup.py bdist_rpm --install-script=rpm-install.sh
}

main "$@"
