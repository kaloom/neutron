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

# Usage: publish-rpms.sh <PATH-TO-RPMS> <ARTIFACTORY_REPO> <RPM-NAME-PREFIX>
#

RPMS_PATH=$1
ARTIFACTORY_REPO=$2
RPM_NAME=$3

cd ${RPMS_PATH}

for rpmFile in ${RPM_NAME}*.rpm; do
    echo $rpmFile
    which md5sum || exit $?
    which sha1sum || exit $?

    md5Value="`md5sum "$rpmFile"`"
    md5Value="${md5Value:0:32}"
    sha1Value="`sha1sum "$rpmFile"`"
    sha1Value="${sha1Value:0:40}"
    fileName="`basename "$rpmFile"`"

    echo $md5Value $sha1Value $rpmFile

    echo "INFO: Uploading $rpmFile to $targetFolder/$fileName"
    curl -i -X PUT -u ${ARTIFACTORY_USER}:${ARTIFACTORY_PASS} \
     -H "X-Checksum-Md5: $md5Value" \
     -H "X-Checksum-Sha1: $sha1Value" \
     -T "$rpmFile" \
    "${ARTIFACTORY_URL}/${ARTIFACTORY_REPO}/$fileName"

done
