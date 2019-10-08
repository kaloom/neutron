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

from nova.virt.libvirt import driver
from nova.network import os_vif_util

from nova.network import model
from os_vif import objects

from oslo_log import log as logging
LOG = logging.getLogger(__name__)

VIF_DETAILS_VHOSTUSER_KVS_PLUG = 'vhostuser_kvs_plug'

# VIF_TYPE_VHOST_USER = 'vhostuser'
def _nova_to_osvif_vif_vhostuser(vif):
    if vif['details'].get(model.VIF_DETAILS_VHOSTUSER_FP_PLUG, False):
        if vif['details'].get(model.VIF_DETAILS_VHOSTUSER_OVS_PLUG, False):
            profile = objects.vif.VIFPortProfileFPOpenVSwitch(
                interface_id=vif.get('ovs_interfaceid') or vif['id'],
                datapath_type=vif['details'].get(
                    model.VIF_DETAILS_OVS_DATAPATH_TYPE))
            if os_vif_util._is_firewall_required(vif) or vif.is_hybrid_plug_enabled():
                profile.bridge_name = os_vif_util._get_hybrid_bridge_name(vif)
                profile.hybrid_plug = True
            else:
                profile.hybrid_plug = False
                if vif["network"]["bridge"] is not None:
                    profile.bridge_name = vif["network"]["bridge"]
        else:
            profile = objects.vif.VIFPortProfileFPBridge()
            if vif["network"]["bridge"] is not None:
                profile.bridge_name = vif["network"]["bridge"]
        obj = os_vif_util._get_vif_instance(vif, objects.vif.VIFVHostUser,
                        plugin="vhostuser_fp",
                        vif_name= os_vif_util.get_vif_name(vif),
                        port_profile=profile)
        os_vif_util._set_vhostuser_settings(vif, obj)
        return obj
    elif vif['details'].get(model.VIF_DETAILS_VHOSTUSER_OVS_PLUG, False):
        profile = objects.vif.VIFPortProfileOpenVSwitch(
            interface_id=vif.get('ovs_interfaceid') or vif['id'],
            datapath_type=vif['details'].get(
                model.VIF_DETAILS_OVS_DATAPATH_TYPE))
        vif_name = ('vhu' + vif['id'])[:model.NIC_NAME_LEN]
        obj = os_vif_util._get_vif_instance(vif, objects.vif.VIFVHostUser,
                                port_profile=profile, plugin="ovs",
                                vif_name=vif_name)
        if vif["network"]["bridge"] is not None:
            obj.bridge_name = vif["network"]["bridge"]
        os_vif_util._set_vhostuser_settings(vif, obj)
        return obj
    elif vif['details'].get(model.VIF_DETAILS_VHOSTUSER_VROUTER_PLUG, False):
        obj = os_vif_util._get_vif_instance(vif, objects.vif.VIFVHostUser,
                                plugin="contrail_vrouter",
                                vif_name=os_vif_util._get_vif_name(vif))
        os_vif_util._set_vhostuser_settings(vif, obj)
        return obj
    #added for kaloom kvs
    elif vif['details'].get(VIF_DETAILS_VHOSTUSER_KVS_PLUG, False):
        profile = objects.vif.VIFPortProfileOpenVSwitch(
            interface_id=vif.get('ovs_interfaceid') or vif['id'],
            datapath_type='')
        vif_name = ('vhu' + vif['id'])[:model.NIC_NAME_LEN]
        obj = os_vif_util._get_vif_instance(vif, objects.vif.VIFVHostUser,
                                port_profile=profile, plugin="kvs_kaloom",
                                vif_name=vif_name)
        if vif["network"]["bridge"] is not None:
            obj.bridge_name = vif["network"]["bridge"]
        os_vif_util._set_vhostuser_settings(vif, obj)
        return obj
    else:
        raise NotImplementedError()


class LibvirtDriverKaloom(driver.LibvirtDriver):
    def __init__(self, virtapi, read_only=False):
        super(LibvirtDriverKaloom, self).__init__(virtapi, read_only)
        os_vif_util._nova_to_osvif_vif_vhostuser = _nova_to_osvif_vif_vhostuser # existing function modified to support vif_type=vhostuser, vif_details={vhostuser_kvs_plug:'True'}
        LOG.info("LibvirtDriverKaloom get loaded.")

#a = LibvirtDriverKaloom(virtapi = None)
#a.vif_driver.plug(instance=None, vif = {'type':'ovs'})
