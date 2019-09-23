# Copyright 2019 Kaloom, Inc.  All rights reserved.
# Copyright 2012 Cisco Systems, Inc.
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
import os, pwd, grp
import selinux

import libvirt
from lxml import objectify

from neutron_lib import constants as n_const
from neutron.agent import rpc as agent_rpc
from neutron.common import rpc as common_rpc
from oslo_log import log
import oslo_messaging

from kaloom_kvs_agent.common \
     import constants as a_const

LOG = log.getLogger(__name__)

class kvsPluginApi(agent_rpc.PluginApi):

    def __init__(self, topic):
        target = oslo_messaging.Target(topic=topic, version='1.0')
        self.client = common_rpc.get_client(target)

    def get_knid(self, context, network_id):
        cctxt = self.client.prepare()
        LOG.info(_("KVS: RPC get_knid is called for network_id: %s."), network_id)
        return cctxt.call(context, 'get_knid', network_id=network_id)

    def get_mac(self, context, port_id):
        cctxt = self.client.prepare()
        LOG.info(_("KVS: RPC get_mac is called for port_id: %s."), port_id)
        return cctxt.call(context, 'get_mac', port_id=port_id)

    def get_parent_port_info(self, context, trunk_id):
        cctxt = self.client.prepare()
        LOG.info(_("KVS: RPC get_parent_port_info is called for trunk_id: %s."), trunk_id)
        return cctxt.call(context, 'get_parent_port_info', trunk_id=trunk_id)

    def get_info_sub_port(self, context, subport_ids):
        cctxt = self.client.prepare()
        LOG.info(_("KVS: RPC get_info_sub_port is called for subport_ids: %s."), subport_ids)
        return cctxt.call(context, 'get_info_sub_port', port_ids=subport_ids)


def get_tap_device_name(interface_id):
    """Convert port ID into device name format expected by KVS"""
    if not interface_id:
        LOG.warning("Invalid Interface ID, will lead to incorrect "
                    "tap device name")
    tap_device_name = (n_const.TAP_DEVICE_PREFIX +
                       interface_id[:a_const.RESOURCE_ID_LENGTH])
    return tap_device_name

def mac2ipv6(mac):
    # only accept MACs separated by a colon
    parts = mac.split(":")

    # modify parts to match IPv6 value
    parts.insert(3, "ff")
    parts.insert(4, "fe")
    parts[0] = "%x" % (int(parts[0], 16) ^ 2)

    # format output
    ipv6Parts = []
    for i in range(0, len(parts), 2):
        ipv6Parts.append("".join(parts[i:i+2]))
    ipv6 = "fe80::%s" % (":".join(ipv6Parts))
    return ipv6

def get_libvirt_capabilities_secmodel():
    # secmodel defined in /etc/libvirt/qemu.conf  
    # supports security_driver as [ "selinux", "apparmor" ]  
    # The DAC security driver is always enabled;
    # SELinux basic confinement (root:system_r:qemu_t), SELinux sVirt confinement (system_u:system_r:svirt_t:s0), AppArmor sVirt confinement..

    result = {}
    conn = libvirt.openReadOnly('qemu:///system')
    if conn == None:
       LOG.error("Failed to open connection to qemu:///system")
       return None
    raw_xml = conn.getCapabilities()
    conn.close()
    LOG.debug('Capabilities:\n %s', raw_xml)

    xml_root = objectify.fromstring(raw_xml).getroottree()
    secmodels = xml_root.findall('//secmodel')
    for secmodel in secmodels:
       model = secmodel.find("model")
       result[model]={}
       baselabels = secmodel.findall('baselabel')
       for baselabel in baselabels:
          type = baselabel.attrib['type']
          label = baselabel.text
          result[model][type] = label
    return result

def get_qemu_process_user():
    dac_model = 'dac'
    virt_type = 'kvm' # read from /etc/nova/nova.conf
    secmodels = get_libvirt_capabilities_secmodel()
    if secmodels is None:
       return None
    LOG.debug('libvirt secmodels %s', secmodels)
    #{'selinux': {'kvm': 'system_u:system_r:svirt_t:s0', 'qemu': 'system_u:system_r:svirt_tcg_t:s0'}, 'dac': {'kvm': '+107:+107', 'qemu': '+107:+107'}}
    if dac_model in secmodels.keys() and virt_type in secmodels[dac_model].keys():
       user_group =  secmodels[dac_model][virt_type]
       user = user_group.split(':')[0]
       if user[0] == '+': #leading + forces numeric uid
          uid = int(user[1:])
          return pwd.getpwuid(uid).pw_name
       else:
          return user
    else:
       return None

def check_permission(path):
    #check selinux context_t 
    if selinux.is_selinux_enabled():
        context_t = selinux.getfilecon(path)[1].split(":")[2]
        #openstack-selinux already supports /var/run folder with var_run_t context.
        #for other folder, we expect virt_cache_t context.
        if not (((path == '/var/run' or path.startswith('/var/run/')) and context_t == 'var_run_t') or context_t == 'virt_cache_t'):
           msg = "selinux context is not properly configured on %s" % (path)
           return False, msg

    #check rx permission for qemu-kvm-user 
    ##user that the (libvirt managed) QEMU VM(process)s are run as: that utimately requires permission on vhost sockets.
    ##The default user is "qemu" for RHEL7.5 (the comment in /etc/libvirt/qemu.conf seems wrong, which says default is root)
    ##ps -ef shows |grep qemu, confirms the user.
    ##We are checking "libvirt capabilities" to find out the user.
    qemu_kvm_user = get_qemu_process_user()
    if qemu_kvm_user is None:
        msg = "qemu_kvm_user couldnot be found."
        return False, msg
    uid_qemu_kvm_user = pwd.getpwnam(qemu_kvm_user).pw_uid
    gid_groups_qemu_kvm_user = [g.gr_gid for g in grp.getgrall() if qemu_kvm_user in g.gr_mem]

    stat_obj = os.stat(path)
    uid_path = stat_obj.st_uid
    gid_path = stat_obj.st_gid
    chmod_path = oct(stat_obj.st_mode)[-3:] #e.g. '755'

    #user falls in user/group/other
    if uid_path == uid_qemu_kvm_user:
        index = 0
    elif gid_path in gid_groups_qemu_kvm_user:
        index = 1
    else:
        index = 2
    #check rx permission
    if chmod_path[index] in ['5', '7']:
        return True, ''
    else:
        msg = "%s does not have read/execute permission set on %s" % (qemu_kvm_user, path)
        return False, msg
