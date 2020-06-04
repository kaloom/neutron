# Copyright 2019 Kaloom, Inc.  All rights reserved.
# Derived from nova/network/linux_net.py
#
# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
import os
import binascii
from os_vif.internal import ip as ip_lib
from oslo_concurrency import processutils
from vif_plug_kaloom_kvs import privsep
from vif_plug_kaloom_kvs import exception

from neutron_lib import constants as n_const

import grpc
# import the generated classes
from kaloom_kvs_agent.stub import service_pb2, service_pb2_grpc
from kaloom_kvs_agent.stub import kvs_msg_pb2, ports_pb2, error_pb2


from oslo_log import log as logging
from vif_plug_kaloom_kvs import constants as a_const
LOG = logging.getLogger(__name__)

def vhost_sock_set_ownership(path,vhost_owner):
   (user,group)= vhost_owner.split(":")
   full_args = ['chown',"%s:%s"%(user,group),path]
   try:
      return processutils.execute(*full_args)
   except Exception as e:
      LOG.error("Unable to execute %(cmd)s. Exception: %(exception)s",
                  {'cmd': full_args, 'exception': e})
      raise exception.AgentError(method=full_args)

def vhost_sock_set_permissions(path, vhost_perm):
   full_args = ['chmod',vhost_perm, path]
   try:
      return processutils.execute(*full_args)
   except Exception as e:
      LOG.error("Unable to execute %(cmd)s. Exception: %(exception)s",
                  {'cmd': full_args, 'exception': e})
      raise exception.AgentError(method=full_args)

def delete_mac_entry(knid, mac):
    LOG.info("Deleting MAC entry for VHOST %s", mac)
    macbytes = binascii.unhexlify(mac.replace(b':', b''))

    # open a gRPC channel
    channel = grpc.insecure_channel(a_const.KVS_SERVER)

    # create a stub (client)
    stub = service_pb2_grpc.kvsStub(channel)

    req = kvs_msg_pb2.DeleteStaticMacEntryRequest()
    req.Knid = knid
    req.MACAddress = macbytes

    # make the call
    response = stub.DeleteStaticMacEntry(req)

    #close channel
    channel.close()
    if response.error.Code == a_const.noError:
        return True
    else:
        LOG.error("gRPC Error during delete_mac_entry:  Error Code: %(code)s  Errormsg: %(msg)s ",
                 {'code': response.error.Code, 'msg': response.error.Errormsg})
        return False

@privsep.vif_plug.entrypoint
def create_kvs_vhost_port(vhost_server_path, mac, mtu=None):
    #create vif
    LOG.info("creating kvs vhost port")

    # open a gRPC channel
    channel = grpc.insecure_channel(a_const.KVS_SERVER)

    # create a stub (client)
    stub = service_pb2_grpc.kvsStub(channel)

    req=kvs_msg_pb2.AddPortRequest()
    req.Type.vHostPortConfig.Path = vhost_server_path
    #req.Type.vHostPortConfig.MACAddress = mac
    #req.Type.vHostPortConfig.MTU = mtu
    #req.Type.vHostPortConfig.NumQueues =
    #req.Type.vHostPortConfig.QueueSize =

    # make the call
    response=stub.AddPort(req)

    #close channel
    channel.close()

    if response.error.Code == a_const.noError:
        # group/permissions for vhost-user socket (required to work with libvirt/qemu)
        vhost_sock_set_ownership(vhost_server_path, a_const.VHOST_SOCK_OWNER)
        vhost_sock_set_permissions(vhost_server_path, a_const.VHOST_SOCK_PERM)

        LOG.info("vhost port created: vhost_server_path: %(vhost_server_path)s PortID: %(port)s ",
                 {'vhost_server_path': vhost_server_path, 'port': response.PortID})
        return True
    else:
        LOG.error("gRPC Error during create_kvs_vhost_port:  Error Code: %(code)s  Errormsg: %(msg)s ",
                 {'code': response.error.Code, 'msg': response.error.Errormsg})
        return False

def listPorts(socket_dir,filePrefix):
    # open a gRPC channel
    channel = grpc.insecure_channel(a_const.KVS_SERVER)

    # create a stub (client)
    stub = service_pb2_grpc.kvsStub(channel)

    # create a valid request message: get ports
    req = kvs_msg_pb2.GetPortsRequest()
    # make the call
    response = stub.GetPorts(req)
    #close channel
    channel.close()
    #print(response)
    if response.error.Code != 0:
       LOG.error("Error on grpc GetPorts call: Code %(code)s, Message %(msg)s",{'code':response.error.Code, 'msg':response.error.Errormsg})
    else:
       devices = {}
       pathPrefix=os.path.join(socket_dir,filePrefix)
       for Port in response.Ports:
          if Port.Type.WhichOneof("PortConfig") == "vHostPortConfig" and \
                 Port.Type.vHostPortConfig.Path.startswith(pathPrefix):
             #print Port.AdminState
             #print Port.PortID
             PortName=Port.Type.vHostPortConfig.Path.replace(pathPrefix,'')
             devices[PortName]=Port.PortID
          elif Port.Type.WhichOneof("PortConfig") == "vDevPortConfig" and \
                 Port.Type.vDevPortConfig.IfaceName.startswith(n_const.TAP_DEVICE_PREFIX):
             PortName=Port.Type.vDevPortConfig.IfaceName
             devices[PortName]=Port.PortID
       return devices

def delete_kvs_port(kvs_device_name, socket_dir=None,file_prefix=None):
    LOG.info("deleting kvs vhost/vdev port")
    if socket_dir is None:
        socket_dir = os.path.dirname(kvs_device_name)
    if file_prefix is None:
        file_prefix= a_const.KVS_VHOSTUSER_PREFIX

    ports = listPorts(socket_dir, file_prefix)

    pathPrefix = os.path.join(socket_dir, file_prefix)
    PortName = kvs_device_name.replace(pathPrefix, '')
    port_index = None
    if PortName in ports.keys():
        port_index = ports[PortName]

    if port_index is None:
        LOG.error("port_index could not found for vhost/vdev %s", kvs_device_name)
        return False

    # open a gRPC channel
    channel = grpc.insecure_channel(a_const.KVS_SERVER)

    # create a stub (client)
    stub = service_pb2_grpc.kvsStub(channel)

    #detach from network, if already attached.
    req_detach = kvs_msg_pb2.DetachPortFromL2NetworkRequest()
    req_detach.PortID = port_index
    #req_detach.VlanID =

    #make the call
    response_detach = stub.DetachPortFromL2Network(req_detach)

    if response_detach.error.Code != a_const.noError and response_detach.error.Code != a_const.PortNotAttached:
        LOG.error("gRPC Error during detach_network on vhost/vdev %(kvs_device_name)s:  Error Code: %(code)s"
                  " Errormsg: %(msg)s ", {'kvs_device_name': kvs_device_name, 'code': response_detach.error.Code,
                                          'msg': response_detach.error.Errormsg})

    # delete port
    req=kvs_msg_pb2.DeletePortRequest()
    req.PortID = port_index

    # make the call
    response = stub.DeletePort(req)

    #close channel
    channel.close()

    if response.error.Code == a_const.noError:
        return True
    else:
        LOG.error("gRPC Error during delete vhost/vdev %(kvs_device_name)s:  Error Code: %(code)s  Errormsg: %(msg)s ",
                      {'kvs_device_name': kvs_device_name, 'code': response.error.Code, 'msg': response.error.Errormsg})
        return False

