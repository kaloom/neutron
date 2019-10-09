#!/bin/bash
#
# This script publishes neutron artifacts including RPMs and containers
# to different repositories. The following variables are expected to be 
# set to define repositories to store binaries.
#
# RPMS_DEVELOP: Development RPM repository
# RPMS_SNAPSHOTS: Snapshots RPM repository 
# RPMS_RELEASE: Releases RPM repository
# RPMS_USER: Username for RPM repositories
# RPMS_PASS: Password for RPM repositories
# RPMS_URL: URL for RPM repositories
#
# REGISTRY_DEVELOP: Development containers registry
# REGISTRY_SNAPSHOTS: Snapshots containers registry
# REGISTRY_RELEASE: Releases container registry
# REGISTRY_USER: Username for containers registries
# REGISTRY_PASS: Password for containers registries

readonly VERSION=$(ls build/networking_kaloom/dist/ | grep noarch | cut -d'-' -f2)
readonly BRANCH=$(git rev-parse --abbrev-ref HEAD)

set_binary_repos() {
	if [[ ${BRANCH} == "master" ]] && [[ ${VERSION} =~ ".dev" ]]; then
		RPMS_REPO=${RPMS_SNAPSHOTS}
		REGISTRY_REPO=${REGISTRY_SNAPSHOTS}
	elif [[ ${BRANCH} != "master" ]] && [[ ${VERSION} =~ ".dev" ]]; then
		RPMS_REPO=${RPMS_DEVELOP}
		REGISTRY_REPO=${REGISTRY_DEVELOP}
	elif [[ ${BRANCH} == "master" ]] && ! [[ ${VERSION} =~ ".dev" ]]; then
		RPMS_REPO=${RPMS_RELEASE}
		REGISTRY_REPO=${REGISTRY_RELEASE}
	else
		echo "Error: Unable to extract version of built RPMs"
		exit 1
	fi
	echo "INFO: Binary repositories used: $RPMS_URL/$RPMS_REPO $REGISTRY_REPO"
}

publish_rpms() {
	RPM_PATHS=$(find build -name *.rpm)
	for rpmFile in ${RPM_PATHS}; do
		which md5sum || exit $?
		which sha1sum || exit $?

		md5Value="`md5sum "$rpmFile"`"
		md5Value="${md5Value:0:32}"
		sha1Value="`sha1sum "$rpmFile"`"
		sha1Value="${sha1Value:0:40}"
		fileName="`basename "$rpmFile"`"

		echo "INFO: Uploading $rpmFile to ${RPMS_URL}/${RPMS_REPO}/$fileName"
		curl -i -X PUT -u ${RPMS_USER}:${RPMS_PASS} \
			-H "X-Checksum-Md5: $md5Value" \
			-H "X-Checksum-Sha1: $sha1Value" \
			-T "$rpmFile" \
			"${RPMS_URL}/${RPMS_REPO}/$fileName"
	done
}

publish_containers() {
	docker tag rhosp12/openstack-neutron-server-kaloom-plugin:${VERSION} ${REGISTRY_REPO}/rhosp13/openstack-neutron-server-kaloom-plugin:${VERSION}
	echo "$REGISTRY_PASS" | docker login -u "$REGISTRY_USER" --password-stdin ${REGISTRY_REPO}
	echo "INFO: Pushing container: ${REGISTRY_REPO}/rhosp13/openstack-neutron-server-kaloom-plugin:${VERSION}"
	docker push ${REGISTRY_REPO}/rhosp13/openstack-neutron-server-kaloom-plugin:${VERSION}
}

main() {
	set_binary_repos
	publish_rpms
	publish_containers
}

main "$@"
