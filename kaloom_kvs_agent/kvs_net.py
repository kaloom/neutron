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

import binascii
import os
import socket,struct,netaddr
from oslo_log import log as logging
from neutron_lib import constants as n_const
from neutron.agent.l3 import namespaces
import grpc
# import the generated classes
from kaloom_kvs_agent.stub import service_pb2, service_pb2_grpc
from kaloom_kvs_agent.stub import kvs_msg_pb2, ports_pb2, error_pb2

from kaloom_kvs_agent.common \
     import constants as a_const

LOG = logging.getLogger(__name__)

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
    if response.error.Code != a_const.noError:
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
                 Port.Type.vDevPortConfig.IfaceName.startswith((n_const.TAP_DEVICE_PREFIX, namespaces.INTERNAL_DEV_PREFIX, namespaces.EXTERNAL_DEV_PREFIX )):
             PortName=Port.Type.vDevPortConfig.IfaceName
             devices[PortName]=Port.PortID
       return devices


def getPort(kvs_device_name, socket_dir, file_prefix):
    path_prefix = os.path.join(socket_dir, file_prefix)
    port_name = kvs_device_name.replace(path_prefix , '')
    ports = listPorts(socket_dir, file_prefix)
    port_index = None
    if port_name in ports.keys():
        port_index = ports[port_name]
    return port_index

def getPort_partialmatch(part_device_name, socket_dir, file_prefix):
    ports = listPorts(socket_dir, file_prefix)
    port_index = None
    prefixes=[namespaces.EXTERNAL_DEV_PREFIX, namespaces.INTERNAL_DEV_PREFIX]
    for prefix in prefixes:
       port_name = prefix + part_device_name
       if port_name in ports.keys():
          port_index = ports[port_name]
          return port_name, port_index

def get_interface_ifindex(socket_dir, socket_file):
    # open a gRPC channel
    channel = grpc.insecure_channel(a_const.KVS_SERVER)

    # create a stub (client)
    stub = service_pb2_grpc.kvsStub(channel)

    # create a valid request message: get port ID
    req=kvs_msg_pb2.GetPortIDRequest()
    req.Type.vHostPortConfig.Path = os.path.join(socket_dir,socket_file)

    # make the call
    response = stub.GetPortID(req)
    #close
    channel.close()
    #print(response)
    if response.error.Code != a_const.noError:
        LOG.error("Error on grpc GetPorts call: Code %(code)s, Message %(msg)s",{'code':response.error.Code, 'msg':response.error.Errormsg})
    else:
        return response.PortID


def add_mac_entry(knid, mac, port_index, vlan=0):
    LOG.info("Adding MAC entry for VHOST %s", mac)
    macbytes = binascii.unhexlify(mac.replace(b':', b''))

    # open a gRPC channel
    channel = grpc.insecure_channel(a_const.KVS_SERVER)

    # create a stub (client)
    stub = service_pb2_grpc.kvsStub(channel)

    req=kvs_msg_pb2.AddStaticLocalIfaceMacEntryRequest()
    req.Knid = knid
    req.MACAddress = macbytes
    req.PortID = port_index
    req.VlanID = vlan

    # make the call
    response = stub.AddStaticLocalIfaceMacEntry(req)

    #close
    channel.close()

    if response.error.Code == a_const.noError:
        LOG.info("AddStaticLocalIfaceMacEntry successful:  KNID: %(knid)s  MAC: %(mac)s port: %(port_index)s VLAN:%(vlan)s ",
                {'knid': knid, 'mac': mac, 'port_index': port_index, 'vlan':vlan})
        return True
    else:
        LOG.error("gRPC Error during add_mac_entry:  Error Code: %(code)s  Errormsg: %(msg)s ",
                 {'code': response.error.Code, 'msg': response.error.Errormsg})
        return False

def delete_mac_entry(knid, mac):
    LOG.info("Deleting MAC entry for VHOST %s", mac)
    macbytes = binascii.unhexlify(mac.replace(b':', b''))

    # open a gRPC channel
    channel = grpc.insecure_channel(a_const.KVS_SERVER)

    # create a stub (client)
    stub = service_pb2_grpc.kvsStub(channel)

    req=kvs_msg_pb2.DeleteStaticMacEntryRequest()
    req.Knid = knid
    req.MACAddress = macbytes

    # make the call
    response = stub.DeleteStaticMacEntry(req)

    #close
    channel.close()

    if response.error.Code == a_const.noError:
        LOG.info("DeleteStaticMacEntryRequest successful:  KNID: %(knid)s  MAC: %(mac)s",
                {'knid': knid, 'mac': mac})
        return True
    else:
        LOG.error("gRPC Error during delete_mac_entry:  Error Code: %(code)s  Errormsg: %(msg)s ",
                 {'code': response.error.Code, 'msg': response.error.Errormsg})
        return False


def _attach_interface(kvs_device_name, port_index, knid, vlan=0):
        # open a gRPC channel
        channel = grpc.insecure_channel(a_const.KVS_SERVER)

        # create a stub (client)
        stub = service_pb2_grpc.kvsStub(channel)

        # create a valid request message: AttachPortToL2NetworkRequest
        req = kvs_msg_pb2.AttachPortToL2NetworkRequest()
        req.PortID = port_index
        req.VlanID = vlan
        req.Knid = knid

        # make the call
        response = stub.AttachPortToL2Network(req)

        # close
        channel.close()
        #print(response)
        if response.error.Code == a_const.noError:
            LOG.info("AttachPortToL2Network successful: kvs_device_name %(device)s, knid %(knid)s, vlan %(vlan)s",{'device':kvs_device_name, 'knid':knid, 'vlan':vlan})
            return True, port_index
        elif response.error.Code == a_const.AlreadyExists: #already attached to network
            LOG.info("AttachPortToL2Network call: Code %(code)s, Message %(msg)s",{'code':response.error.Code, 'msg':response.error.Errormsg})
            return True, port_index # say successful
        else:
            LOG.error("Error on grpc AttachPortToL2Network call: Code %(code)s, Message %(msg)s",{'code':response.error.Code, 'msg':response.error.Errormsg})
            return False, port_index

def attach_interface(network_id, network_type,
                          physical_network, knid,
                          kvs_device_name, device_owner, mtu, socket_dir,filePrefix):
    LOG.info("inside attach_interface")

    ports = listPorts(socket_dir,filePrefix)
    pathPrefix = os.path.join(socket_dir,filePrefix)
    #if kvs_device_name.startswith((n_const.TAP_DEVICE_PREFIX, namespaces.INTERNAL_DEV_PREFIX, namespaces.EXTERNAL_DEV_PREFIX )):
    #    PortName=kvs_device_name
    #else:
    #    PortName=kvs_device_name.replace(pathPrefix,'')
    PortName = kvs_device_name.replace(pathPrefix,'')
    port_index = None
    if PortName in ports.keys():
        port_index = ports[PortName]
    
    if port_index is None:
        LOG.error("port_index could not found for vhost/vdev %s",kvs_device_name)
        return False, port_index
    else:
        return _attach_interface(kvs_device_name, port_index, knid)

def configurePort(vhost_path, admin_state_up):
    # open a gRPC channel
    channel = grpc.insecure_channel(a_const.KVS_SERVER)

    # create a stub (client)
    stub = service_pb2_grpc.kvsStub(channel)

    # create a valid request message: ConfigurePortRequest
    req=kvs_msg_pb2.ConfigurePortRequest()
    #req.PortID= ##TODO
    req.Conf.MACAddress="00:00:00:00:00:00"
    req.Conf.MTU=0
    if admin_state_up:
       req.Conf.AdminState="AdminStateUp"
    else:
       req.Conf.AdminState="AdminStateDown"

    # make the call
    response = stub.ConfigurePort(req)
    #close
    channel.close()
    #print(response)
    if response.error.Code != a_const.noError:
        LOG.error("Error on grpc ConfigurePortRequest call: Code %(code)s, Message %(msg)s",{'code':response.error.Code, 'msg':response.error.Errormsg})

def create_kvs_vdev_port(device_name, mac, mtu=None):
    #create vif
    LOG.info("creating kvs vdev port")

    # open a gRPC channel
    channel = grpc.insecure_channel(a_const.KVS_SERVER)

    # create a stub (client)
    stub = service_pb2_grpc.kvsStub(channel)

    req=kvs_msg_pb2.AddPortRequest()
    req.Type.vDevPortConfig.IfaceName = device_name
    if mac:
       macbytes = binascii.unhexlify(mac.replace(b':', b''))
       LOG.debug("%s", mac)
       req.Type.vDevPortConfig.MACAddress = macbytes
    if mtu:
       req.Type.vDevPortConfig.MTU = mtu

    # make the call
    response=stub.AddPort(req)

    #close channel
    channel.close()

    if response.error.Code == a_const.noError:
        return True
    else:
        LOG.error("gRPC Error during create_kvs_vdev_port:  Error Code: %(code)s  Errormsg: %(msg)s ",
                 {'code': response.error.Code, 'msg': response.error.Errormsg})
        return False

def _detach_interface(kvs_device_name, port_index, vlan=0):
    # open a gRPC channel
    channel = grpc.insecure_channel(a_const.KVS_SERVER)

    # create a stub (client)
    stub = service_pb2_grpc.kvsStub(channel)

    #detach from network, if already attached.
    req_detach = kvs_msg_pb2.DetachPortFromL2NetworkRequest()
    req_detach.PortID = port_index
    req_detach.VlanID = vlan

    #make the call
    response_detach = stub.DetachPortFromL2Network(req_detach)

    if response_detach.error.Code != a_const.noError and response_detach.error.Code != a_const.PortNotAttached:
        LOG.error("gRPC Error during detach_network on vhost/vdev %(kvs_device_name)s:  Error Code: %(code)s"
                  " Errormsg: %(msg)s ", {'kvs_device_name': kvs_device_name, 'code': response_detach.error.Code,
                                          'msg': response_detach.error.Errormsg})

    #close channel
    channel.close()


def delete_kvs_port(kvs_device_name, socket_dir=None,file_prefix=None):
    LOG.info("deleting kvs vdev port")
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

    # detach interface
    _detach_interface(kvs_device_name, port_index)

    # open a gRPC channel
    channel = grpc.insecure_channel(a_const.KVS_SERVER)

    # create a stub (client)
    stub = service_pb2_grpc.kvsStub(channel)

    # delete port
    req=kvs_msg_pb2.DeletePortRequest()
    req.PortID = port_index

    # make the call
    response=stub.DeletePort(req)

    #close channel
    channel.close()

    if response.error.Code == a_const.noError:
        return True
    else:
        LOG.error("gRPC Error during delete vhost/vdev %(kvs_device_name)s:  Error Code: %(code)s  Errormsg: %(msg)s ",
                 {'kvs_device_name': kvs_device_name, 'code': response.error.Code, 'msg': response.error.Errormsg})
        return False


def add_anti_spoofing_rule(port_index, mac, ip):
    # open a gRPC channel
    channel = grpc.insecure_channel(a_const.KVS_SERVER)

    # create a stub (client)
    stub = service_pb2_grpc.kvsStub(channel)

    # create a valid request message: AddAntiSpoofingRuleRequest
    req=kvs_msg_pb2.AddAntiSpoofingRuleRequest()
    req.PortID = port_index
    if mac:
       LOG.debug("%s", mac)
       macbytes = binascii.unhexlify(mac.replace(b':', b''))
       req.Rule.MACAddress = macbytes
    if ip:
       if netaddr.IPNetwork(ip).version == 4 :
           ipbytes = socket.inet_aton(ip)
       elif netaddr.IPNetwork(ip).version == 6 :
           ipbytes = socket.inet_pton(socket.AF_INET6, ip)
       req.Rule.IP = ipbytes

    # make the call
    response = stub.AddAntiSpoofingRule(req)
    #close
    channel.close()
    #print(response)
    if response.error.Code != a_const.noError:
        LOG.error("Error on grpc AddAntiSpoofingRuleRequest call: Code %(code)s, Message %(msg)s",
                  {'code':response.error.Code, 'msg':response.error.Errormsg})
    else:
        LOG.info("add_anti_spoofing_rule on port_index %s for mac %s and ip %s ",
                 port_index, mac, ip)

def delete_anti_spoofing_rule(port_index, mac, ip):
    # open a gRPC channel
    channel = grpc.insecure_channel(a_const.KVS_SERVER)

    # create a stub (client)
    stub = service_pb2_grpc.kvsStub(channel)

    # create a valid request message: DeleteAntiSpoofingRuleRequest
    req = kvs_msg_pb2.DeleteAntiSpoofingRuleRequest()
    req.PortID = port_index
    if mac:
       LOG.debug("%s", mac)
       macbytes = binascii.unhexlify(mac.replace(b':', b''))
       req.Rule.MACAddress = macbytes

    if ip:
       if netaddr.IPNetwork(ip).version == 4 :
           ipbytes = socket.inet_aton(ip)
       elif netaddr.IPNetwork(ip).version == 6 :
           ipbytes = socket.inet_pton(socket.AF_INET6, ip)
       LOG.debug("%s", ip)
       req.Rule.IP = ipbytes

    # make the call
    response = stub.DeleteAntiSpoofingRule(req)
    #close
    channel.close()
    #print(response)
    if response.error.Code != a_const.noError:
        LOG.error("Error on grpc DeleteAntiSpoofingRule call: Code %(code)s, Message %(msg)s",
                  {'code':response.error.Code, 'msg':response.error.Errormsg})
    else:
        LOG.info("delete_anti_spoofing_rule on port_index %s for mac %s and ip %s ",
                    port_index, mac, ip)

def list_anti_spoofing_rules(port_index, vlan = None):
    # open a gRPC channel
    channel = grpc.insecure_channel(a_const.KVS_SERVER)

    # create a stub (client)
    stub = service_pb2_grpc.kvsStub(channel)

    # create a valid request message: GetAntiSpoofingRulesRequest
    req=kvs_msg_pb2.GetAntiSpoofingRulesRequest()
    req.PortID = port_index
    #vlan specific spoofing rules or for all vlans TODO

    # make the call
    response = stub.GetAntiSpoofingRules(req)
    #close
    channel.close()
    #print(response)
    if response.error.Code != a_const.noError:
        LOG.error("Error on grpc GetAntiSpoofingRules call: Code %(code)s, Message %(msg)s",
                  {'code':response.error.Code, 'msg':response.error.Errormsg})
        return None
    else:
        pairs = []
        for rule in response.Rules:
            if len(rule.IP) == 4: ##4 bytes of IPv4
               ip = socket.inet_ntoa(rule.IP)
            elif len(rule.IP) == 16: ##16 bytes of IPv6
               ip = socket.inet_ntop(socket.AF_INET6, rule.IP)
            mac = "%02x:%02x:%02x:%02x:%02x:%02x" % struct.unpack("BBBBBB", rule.MACAddress)
            pair = {"ip": ip , "mac": mac}
            pairs.append(pair)
        return pairs
