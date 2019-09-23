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

import socket

from oslo_log import log
from oslo_utils import excutils
from oslo_concurrency import lockutils
import xml.dom.minidom
from lxml import objectify

from eventlet import event
from eventlet import greenthread
from eventlet import Timeout
import paramiko #neutron/cmd/eventlet/__init__.py already has monkey_patch() that turns blocking chan.recv into non-blocking (green) mode.
from neutron_lib import worker
from networking_kaloom.ml2.drivers.kaloom.common import constants as kconst

L2T_NS = "urn:ietf:params:xml:ns:yang:ietf-l2-topology"
VL2T_NS = "urn:kaloom:faas:vfabric-l2-topology"
NT_NS = "urn:ietf:params:xml:ns:yang:ietf-network-topology"
NW_NS = "urn:ietf:params:xml:ns:yang:ietf-network"
L3UT_NS = "urn:ietf:params:xml:ns:yang:ietf-l3-unicast-topology"
VL3UT_NS = "urn:kaloom:faas:vfabric-l3-unicast-topology"
VIF_NS = "urn:kaloom:faas:vfabric-interfaces"
VIP_NS = "urn:kaloom:faas:vfabric-ip"
VF_NS = "urn:kaloom:faas:virtual-fabric"

TAG_L2_NODE_ATTR = "{" + L2T_NS + "}" + "l2-node-attributes"
TAG_NW_ATTR_NAME = "{" + L2T_NS + "}" + "name"
TAG_NW_ATTR_KNID = "{" + VL2T_NS + "}" + "KNID"
TAG_TP_ATTR = "{" + NT_NS + "}" + "termination-point"
TAG_TP_ID = "{" + NT_NS + "}" + "tp-id"
TAG_TP_NAME = "{" + VL2T_NS + "}" + "name"

TAG_NODE = "{" + NW_NS + "}" + "node"
TAG_NODE_ID = "{" + NW_NS + "}" + "node-id"
TAG_L3_ATTR = "{" + L3UT_NS + "}" + "l3-node-attributes"
TAG_L3_NAME = "{" + L3UT_NS + "}" + "name"
TAG_L3_NODE_ID = "{" + VL3UT_NS + "}" + "node-id"
TAG_L3_INTERFACE_NAME = "{" + VL3UT_NS + "}" + "interface-name"

TAG_VIF_INTERFACES =  "{" + VIF_NS + "}" + "interfaces"
TAG_VIF_INTERFACE = "{" + VIF_NS + "}" + "interface"
TAG_VIF_NAME = "{" + VIF_NS + "}" + "name"
TAG_VIP_IPV4 = "{" + VIP_NS + "}" + "ipv4"
TAG_VIP_IPV6 = "{" + VIP_NS + "}" + "ipv6"
TAG_VIP_ADDRESS = "{" + VIP_NS + "}" + "address"
TAG_VIP_IP = "{" + VIP_NS + "}" + "ip"
TAG_NT_TP = "{" + NT_NS + "}" + "termination-point"
TAG_NT_SUPPORTING_TP = "{" + NT_NS + "}" + "supporting-termination-point"
TAG_NT_NETWORK_REF = "{" + NT_NS + "}" + "network-ref"
TAG_NT_NODE_REF = "{" + NT_NS + "}" + "node-ref"
TAG_L3T_L3_TP_ATTR= "{" + L3UT_NS + "}" + "l3-termination-point-attributes"
TAG_VL3T_IFNAME="{" + VL3UT_NS + "}" + "interface-name"

TAG_VF_ANNOTATIONS = "{" + VF_NS + "}" + "annotations"
TAG_VF_KEY = "{" + VF_NS + "}" + "the-key"
TAG_VF_VALUE = "{" + VF_NS + "}" + "value"

MESG_HELLO = b'''
<?xml version="1.0" encoding="UTF-8"?>
<hello xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
  <capabilities>
    <capability>urn:ietf:params:netconf:base:1.0</capability>
    <capability>urn:ietf:params:netconf:capability:writable-running:1.0</capability>
    <capability>urn:ietf:params:netconf:capability:candidate:1.0</capability>
    <capability>urn:ietf:params:netconf:capability:confirmed-commit:1.0</capability>
    <capability>urn:ietf:params:netconf:capability:startup:1.0</capability>
    <capability>urn:ietf:params:netconf:capability:rollback-on-error:1.0</capability>
  </capabilities>
</hello>
'''

TERMINATOR = b']]>]]>'

L3_command_dict={
'LIST_ROUTER' : """
<?xml version="1.0" encoding="UTF-8"?>
<rpc message-id="message_id" xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
<get xmlns="urn:ietf:params:xml:ns:netconf:base:1.0" xmlns:l3t="urn:ietf:params:xml:ns:yang:ietf-l3-unicast-topology">
<filter type="subtree">
    <networks xmlns="urn:ietf:params:xml:ns:yang:ietf-network">
        <network>
                <network-id>3</network-id>
                <node>
                   <node-id/>
                   <l3t:l3-node-attributes/>
                </node>
        </network>
    </networks>
</filter>
</get>
</rpc>
""",
'GET_ROUTER_ID' : """
<?xml version="1.0" encoding="UTF-8"?>
<rpc message-id="message_id" xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
<get>
        <filter type="subtree">
    <networks xmlns="urn:ietf:params:xml:ns:yang:ietf-network" xmlns:l3t="urn:ietf:params:xml:ns:yang:ietf-l3-unicast-topology">
        <network>
                <network-id>3</network-id>
                <node>
                  <l3t:l3-node-attributes>
                    <l3t:name>%(name)s</l3t:name>
                  </l3t:l3-node-attributes>
                </node>
        </network>
    </networks>
        </filter>
</get>
</rpc>
""",


'CREATE_ROUTER' : """
<?xml version="1.0" encoding="UTF-8"?>
<rpc message-id="message_id" xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
  <create-router xmlns="urn:kaloom:faas:vfabric-l3-unicast-topology">
    <network-id>3</network-id>
    <name>%(router_name)s</name>
  </create-router>
</rpc>
""",

'DELETE_ROUTER' : """
<?xml version="1.0" encoding="UTF-8"?>
<rpc message-id="message_id" xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
  <delete-router xmlns="urn:kaloom:faas:vfabric-l3-unicast-topology">
    <network-id>3</network-id>
    <node-id>%(router_node_id)s</node-id>
  </delete-router>
</rpc>
""",

'ATTACH_ROUTER' : """
<?xml version="1.0" encoding="UTF-8"?>
<rpc message-id="message_id" xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
  <attach-l3node-to-l2node xmlns="urn:kaloom:faas:vfabric-l3-unicast-topology">
    <l3-network-id>3</l3-network-id>
    <l3-node-id>%(router_node_id)s</l3-node-id>
    <l2-network-id>2</l2-network-id>
    <l2-node-id>%(l2_node_id)s</l2-node-id>
    <mtu>1500</mtu>
  </attach-l3node-to-l2node>
</rpc>
""",

'DETACH_ROUTER' : """
<?xml version="1.0" encoding="UTF-8"?>
<rpc message-id="message_id" xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
  <detach-l3node-from-l2node xmlns="urn:kaloom:faas:vfabric-l3-unicast-topology">
    <l3-network-id>3</l3-network-id>
    <l3-node-id>%(router_node_id)s</l3-node-id>
    <l2-network-id>2</l2-network-id>
    <l2-node-id>%(l2_node_id)s</l2-node-id>
  </detach-l3node-from-l2node>
</rpc>
""",
'addIPv4AddressToInterface' : """
<?xml version="1.0" encoding="UTF-8"?>
<rpc message-id="message_id" xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
 <edit-config>
    <target>
     <running />
   </target>
   <default-operation>none</default-operation>
   <config>
     <networks xmlns="urn:ietf:params:xml:ns:yang:ietf-network">
       <network>
         <network-id>3</network-id>
         <node>
           <node-id>%(router_node_id)s</node-id>
           <interfaces xmlns="urn:kaloom:faas:vfabric-interfaces">
             <interface>
             <name>%(interface_name)s</name>
               <ipv4 xmlns="urn:kaloom:faas:vfabric-ip">
                 <address xmlns:a="urn:ietf:params:xml:ns:netconf:base:1.0" a:operation="create">
                   <ip>%(ip_address)s</ip>
                   <prefix-length>%(prefix_length)s</prefix-length>
                 </address>
               </ipv4>
             </interface>
           </interfaces>
         </node>
       </network>
     </networks>
   </config>
 </edit-config>
</rpc>
""",
'deleteIPv4AddressFromInterface' : """
<?xml version="1.0" encoding="UTF-8"?>
<rpc message-id="message_id" xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
  <edit-config>
     <target>
     <running />
   </target>
   <default-operation>none</default-operation>
    <config xmlns:xc="urn:ietf:params:xml:ns:netconf:base:1.0" xmlns:nd="urn:ietf:params:xml:ns:yang:ietf-network" xmlns:vi="urn:kaloom:faas:vfabric-interfaces" xmlns:vip="urn:kaloom:faas:vfabric-ip">
      <nd:networks>
        <nd:network>
          <nd:network-id>3</nd:network-id>
          <nd:node>
            <nd:node-id>%(router_node_id)s</nd:node-id>
            <vi:interfaces>
              <vi:interface>
                <vi:name>%(interface_name)s</vi:name>
                <vip:ipv4>
                  <vip:address xc:operation="remove">
                    <vip:ip>%(ip_address)s</vip:ip>
                  </vip:address>
                </vip:ipv4>
              </vi:interface>
            </vi:interfaces>
          </nd:node>
        </nd:network>
      </nd:networks>
    </config>
  </edit-config>
</rpc>
""",
'addIPv6AddressToInterface' : """
<?xml version="1.0" encoding="UTF-8"?>
<rpc message-id="message_id" xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
 <edit-config>
    <target>
     <running />
   </target>
   <default-operation>none</default-operation>
   <config>
     <networks xmlns="urn:ietf:params:xml:ns:yang:ietf-network">
       <network>
         <network-id>3</network-id>
         <node>
           <node-id>%(router_node_id)s</node-id>
           <interfaces xmlns="urn:kaloom:faas:vfabric-interfaces">
             <interface>
             <name>%(interface_name)s</name>
               <ipv6 xmlns="urn:kaloom:faas:vfabric-ip">
                 <address xmlns:a="urn:ietf:params:xml:ns:netconf:base:1.0" a:operation="create">
                   <ip>%(ip_address)s</ip>
                   <prefix-length>%(prefix_length)s</prefix-length>
                 </address>
               </ipv6>
             </interface>
           </interfaces>
         </node>
       </network>
     </networks>
   </config>
 </edit-config>
</rpc>
""",
'deleteIPv6AddressFromInterface' : """
<?xml version="1.0" encoding="UTF-8"?>
<rpc message-id="message_id" xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
 <edit-config>
    <target>
     <running />
   </target>
   <default-operation>none</default-operation>
   <config>
     <networks xmlns="urn:ietf:params:xml:ns:yang:ietf-network">
       <network>
         <network-id>3</network-id>
         <node>
           <node-id>%(router_node_id)s</node-id>
           <interfaces xmlns="urn:kaloom:faas:vfabric-interfaces">
             <interface>
             <name>%(interface_name)s</name>
               <ipv6 xmlns="urn:kaloom:faas:vfabric-ip">
                 <address xmlns:a="urn:ietf:params:xml:ns:netconf:base:1.0" a:operation="remove">
                   <ip>%(ip_address)s</ip>
                 </address>
               </ipv6>
             </interface>
           </interfaces>
         </node>
       </network>
     </networks>
   </config>
 </edit-config>
</rpc>
""",
'addIPv4StaticRoute':"""
<?xml version="1.0" encoding="UTF-8"?>
<rpc message-id="message_id" xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
  <edit-config>
     <target>
     <running />
   </target>
   <default-operation>none</default-operation>
    <config xmlns:xc="urn:ietf:params:xml:ns:netconf:base:1.0" xmlns:nd="urn:ietf:params:xml:ns:yang:ietf-network" xmlns:vr="urn:kaloom:faas:vfabric-routing" xmlns:v4ur="urn:kaloom:faas:vfabric-ipv4-unicast-routing">
      <nd:networks>
        <nd:network>
          <nd:network-id>3</nd:network-id>
          <nd:node>
            <nd:node-id>%(router_node_id)s</nd:node-id>
            <vr:routing>
              <vr:control-plane-protocols>
                <vr:control-plane-protocol>
                  <vr:type>static</vr:type>
                  <vr:name>static-routes</vr:name>
                  <vr:static-routes>
                    <v4ur:ipv4>
                      <v4ur:route xc:operation="create">
                        <v4ur:destination-prefix>%(destination_prefix)s</v4ur:destination-prefix>
                        <v4ur:next-hop>
                          <v4ur:next-hop-address>%(next_hop_address)s</v4ur:next-hop-address>
                        </v4ur:next-hop>
                      </v4ur:route>
                    </v4ur:ipv4>
                  </vr:static-routes>
                </vr:control-plane-protocol>
              </vr:control-plane-protocols>
            </vr:routing>
          </nd:node>
        </nd:network>
      </nd:networks>  
    </config>
  </edit-config>
</rpc>
""",
'addIPv6StaticRoute':"""
<?xml version="1.0" encoding="UTF-8"?>
<rpc message-id="message_id" xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
  <edit-config>
     <target>
     <running />
   </target>
   <default-operation>none</default-operation>
    <config xmlns:xc="urn:ietf:params:xml:ns:netconf:base:1.0" xmlns:nd="urn:ietf:params:xml:ns:yang:ietf-network" xmlns:vr="urn:kaloom:faas:vfabric-routing" xmlns:v6ur="urn:kaloom:faas:vfabric-ipv6-unicast-routing">
      <nd:networks>
        <nd:network>
          <nd:network-id>3</nd:network-id>
          <nd:node>
            <nd:node-id>%(router_node_id)s</nd:node-id>
            <vr:routing>
              <vr:control-plane-protocols>
                <vr:control-plane-protocol>
                  <vr:type>static</vr:type>
                  <vr:name>static-routes</vr:name>
                  <vr:static-routes>
                    <v6ur:ipv6>
                      <v6ur:route xc:operation="create">
                        <v6ur:destination-prefix>%(destination_prefix)s</v6ur:destination-prefix>
                        <v6ur:next-hop>
                          <v6ur:next-hop-address>%(next_hop_address)s</v6ur:next-hop-address>
                        </v6ur:next-hop>
                      </v6ur:route>
                    </v6ur:ipv6>
                  </vr:static-routes>
                </vr:control-plane-protocol>
              </vr:control-plane-protocols>
            </vr:routing>
          </nd:node>
        </nd:network>
      </nd:networks>
    </config>
  </edit-config>
</rpc>
""",
'deleteIPv4StaticRoute':"""
<?xml version="1.0" encoding="UTF-8"?>
<rpc message-id="message_id" xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
  <edit-config>
     <target>
     <running />
   </target>
   <default-operation>none</default-operation>
    <config xmlns:xc="urn:ietf:params:xml:ns:netconf:base:1.0" xmlns:nd="urn:ietf:params:xml:ns:yang:ietf-network" xmlns:vr="urn:kaloom:faas:vfabric-routing" xmlns:v4ur="urn:kaloom:faas:vfabric-ipv4-unicast-routing">
      <nd:networks>
        <nd:network>
          <nd:network-id>3</nd:network-id>
          <nd:node>
            <nd:node-id>%(router_node_id)s</nd:node-id>
            <vr:routing>
              <vr:control-plane-protocols>
                <vr:control-plane-protocol>
                  <vr:type>static</vr:type>
                  <vr:name>static-routes</vr:name>
                  <vr:static-routes>
                    <v4ur:ipv4>
                      <v4ur:route xc:operation="remove">
                        <v4ur:destination-prefix>%(destination_prefix)s</v4ur:destination-prefix>
                      </v4ur:route>
                    </v4ur:ipv4>
                  </vr:static-routes>
                </vr:control-plane-protocol>
              </vr:control-plane-protocols>
            </vr:routing>
          </nd:node>
        </nd:network>
      </nd:networks>
    </config>
  </edit-config>
</rpc>
""",
'deleteIPv6StaticRoute':"""
<?xml version="1.0" encoding="UTF-8"?>
<rpc message-id="message_id" xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
  <edit-config>
     <target>
     <running />
   </target>
   <default-operation>none</default-operation>
    <config xmlns:xc="urn:ietf:params:xml:ns:netconf:base:1.0" xmlns:nd="urn:ietf:params:xml:ns:yang:ietf-network" xmlns:vr="urn:kaloom:faas:vfabric-routing" xmlns:v6ur="urn:kaloom:faas:vfabric-ipv6-unicast-routing">
      <nd:networks>
        <nd:network>
          <nd:network-id>3</nd:network-id>
          <nd:node>
            <nd:node-id>%(router_node_id)s</nd:node-id>
            <vr:routing>
              <vr:control-plane-protocols>
                <vr:control-plane-protocol>
                  <vr:type>static</vr:type>
                  <vr:name>static-routes</vr:name>
                  <vr:static-routes>
                    <v6ur:ipv6>
                      <v6ur:route xc:operation="remove">
                        <v6ur:destination-prefix>%(destination_prefix)s</v6ur:destination-prefix>
                      </v6ur:route>
                    </v6ur:ipv6>
                  </vr:static-routes>
                </vr:control-plane-protocol>
              </vr:control-plane-protocols>
            </vr:routing>
          </nd:node>
        </nd:network>
      </nd:networks>
    </config>
  </edit-config>
</rpc>
""",
'RENAME_ROUTER':"""
<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<rpc message-id="message_id" xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
 <edit-config>
    <target>
      <running/>
    </target>
  <default-operation>none</default-operation>
  <config>
    <networks xmlns="urn:ietf:params:xml:ns:yang:ietf-network">
     <network>
       <network-id>3</network-id>
       <node>
         <node-id>%(router_node_id)s</node-id>
         <l3-node-attributes xmlns="urn:ietf:params:xml:ns:yang:ietf-l3-unicast-topology" xmlns:a="urn:ietf:params:xml:ns:netconf:base:1.0" a:operation="merge">
            <name>%(router_name)s</name>
         </l3-node-attributes>
       </node>
     </network>
    </networks>
  </config>
 </edit-config>
</rpc>
""",
'GET_ROUTER_INTERFACE_INFO' : """
<?xml version="1.0" encoding="UTF-8"?>
<rpc message-id="message_id" >
<get xmlns="urn:ietf:params:xml:ns:netconf:base:1.0" xmlns:l3t="urn:ietf:params:xml:ns:yang:ietf-l3-unicast-topology" xmlns:vif="urn:kaloom:faas:vfabric-interfaces" xmlns:nt="urn:ietf:params:xml:ns:yang:ietf-network-topology">
<filter type="subtree">
 <networks xmlns="urn:ietf:params:xml:ns:yang:ietf-network">
  <network>
     <network-id>3</network-id>
     <node>
       <node-id/>
       <l3t:l3-node-attributes>
          <l3t:name>%(router_name)s</l3t:name>
       </l3t:l3-node-attributes>
       <nt:termination-point/>
       <vif:interfaces/>
     </node>
   </network>
 </networks>
</filter>
</get>
</rpc>
""",
}

LOG = log.getLogger(__name__)

class KaloomNetconfRecv(worker.BaseWorker):
    def __init__(self, client, chan):
        super(KaloomNetconfRecv, self).__init__(worker_process_count=1)
        self.client = client
        self.chan = chan
        self.msg_events = {}
        self.msg_events_stale = {}
        self._thread = None
        self._running = False
        self.done = None

    def is_running(self):
        return self._running

    def _on_done(self, gt, *args, **kwargs):
        self._running = False
        #force callbacks not to wait anymore
        self.msg_exception_to_callbacks()

        self._thread = None
        #send done event
        self.done.send(True)

    def start(self):
        if self._running:
            return
        if self._thread is not None:
            self.wait() # wait until running thread complete _on_done

        LOG.debug("kaloom netconf receiver loop started")
        super(KaloomNetconfRecv, self).start()
        self._running = True
        self.done = event.Event()
        self._thread = greenthread.spawn(self._recv_loop)
        self._thread.link(self._on_done)
        greenthread.sleep(0) # yield turn to spawned thread immediately.

    def stop(self, graceful=True):
        self._running = False
        #release recv block by closing chan
        if self.chan is not None:
           self.chan.close()
        if not graceful:
           #kill thread
           self._thread.kill()

    def wait(self):
        return self.done.wait()

    def reset(self):
        self.stop()
        self.wait()
        #don't start here, start will be on first msq queue in add_callback_event 

    def update_chan(self, chan):
        self.chan = chan
 
    def add_callback_event(self, msgid, evt):
        if msgid in self.msg_events.keys():
           error_msg = 'add_callback_event: duplicate msgid %s exists.' % msgid
           LOG.error(error_msg) 
           raise ValueError(error_msg)
        else:
           self.msg_events[msgid] = evt
           # starts receiver thread, if not already running.
           self.start()

    def del_callback_event(self, msgid):
        try:
           self.msg_events.pop(msgid)
        except KeyError:
           LOG.warning('del_callback_event: callback event for msgid %s does not exists.', msgid)

    def msg_exception_to_callbacks(self):
        for msgid in self.msg_events_stale.keys():
            evt = self.msg_events_stale.pop(msgid)
            try:
               evt.send_exception(ValueError('receiver thread terminated'))
            except:
               pass

    def msg_reply(self, msg):
        try:
           msg_xml = objectify.fromstring(msg)
        except Exception as e:
           LOG.error('Error occured: %s while handling received netconf msg %s', e, msg)
           return
        msgid = msg_xml.get('message-id')
        if msgid is None:
           LOG.error('message_id could not be parsed on received netconf msg %s', msg)
           return
        #put the msg on callback evt, of the msgid.
        try:
           evt = self.msg_events.pop(msgid) 
        except KeyError:
           #the caller already could timeout 
           LOG.warning('msg_reply: callback evt could not be found for the msgid %s, possibly timeout.', msgid)
           return
        evt.send(msg)

    def _recv_loop(self):
        while self._running:
           try:
              transport = self.client.get_transport()
              if transport is not None and transport.is_active() and self.chan is not None:
                 """Read replies."""
                 ##TERMINATOR bytes could fall in different buffer chunks. 
                 ##same buffer chunk could have multiple replies.
                 responses=''
                 while len(self.msg_events) > 0:
                   try:
                     response = self.chan.recv(2048) #blocking until any data (paramiko has been patched, yields to avoid starvation)
                     if len(response) == 0: #If a string of length zero is returned, the channel stream has closed.
                         LOG.warning("channel closed, stopping receiver thread.")
                         self.msg_events_stale = self.msg_events
                         self.msg_events = {}
                         self._running = False
                         self.chan = None
                         #no way to check chan status (on caller side), so force to recreate by closing transport
                         self.client.close()
                         break
                     responses = responses + response
                     msgs = responses.split(TERMINATOR)
                     msg_count = len(msgs)
                     #except last msg, which is either '' or incomplete, leftover after last TERMINATOR
                     for i in range(msg_count - 1):
                         self.msg_reply(msgs[i])
                     responses = msgs[msg_count-1] #last msg
                     greenthread.sleep(0) #Yield to avoid starvation
                   except socket.timeout: #timeout on netconf recv
                     #timeout happened only for one msgid, there could be more msgids waiting for response.
                     greenthread.sleep(0) #Yield to avoid starvation

                 if self._running:
                     LOG.debug("no more msg to serve response for, stopping receiver thread.")
                     self._running = False
              else:
                 LOG.warning("no active session to listen for recv, stopping receiver thread.")
                 self.msg_events_stale = self.msg_events
                 self.msg_events = {}
                 self._running = False

           except Exception as e:
               # If any unexpected exception happens we don't want the
               # receiver_loop to exit.
               LOG.error(_LE('Unexpected exception in netconf receiver loop %s', e))

class KaloomNetconf(object):
    def __init__(self, host, port, username, private_key_file, password, timeout_sec = 90):
        self.host = host
        self.port = port
        self.username = username
        self.private_key_file = private_key_file
        self.password = password
        self.timeout_sec = timeout_sec
        self.keepalive_interval_sec = int(timeout_sec * 0.8)
        self.connect_timeout = 20 ##socket connect timeout


        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.chan = None
        self.netconf_session_id = None
        self.msgid = 0
        #self.version = self.get_vfabric_version()
        self.receiver = KaloomNetconfRecv(self.client, self.chan)

    def get_vfabric_version(self):
        tag_schema = '{urn:ietf:params:xml:ns:yang:ietf-netconf-monitoring}schema'
        tag_schema_identifier = "{urn:ietf:params:xml:ns:yang:ietf-netconf-monitoring}identifier"
        tag_schema_version = "{urn:ietf:params:xml:ns:yang:ietf-netconf-monitoring}version"
        req_schema_list_rpc = """
        <?xml version="1.0" encoding="UTF-8"?>
        <rpc message-id="message_id" xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
          <get>
            <filter type="subtree">
              <netconf-state xmlns=
                "urn:ietf:params:xml:ns:yang:ietf-netconf-monitoring">
                <schemas/>
              </netconf-state>
            </filter>
          </get>
        </rpc>
        """
        resp = self._exec_netconf_cmd(req_schema_list_rpc)
        LOG.debug(resp)
        schema_xml_tree = objectify.fromstring(resp).getroottree()
        root = schema_xml_tree.getroot()
        schemas=root.findall(".//"+ tag_schema)
        for schema in schemas:
            idr = schema.find(tag_schema_identifier).text
            version= schema.find(tag_schema_version).text
            if idr == "virtual-fabric":
                LOG.info("vfabric version %s detected", version)
                return version #"2018-06-07" , "2018-09-24"
        return None

    def _read(self):
        responses=''
        try:
            while True:
              response = self.chan.recv(2048) #blocking until any data (paramiko has been patched, yields to avoid starvation)
              responses = responses + response
              index = responses.find(TERMINATOR)
              if index != -1: #found
                 return responses[:index]
        except socket.timeout:
            with excutils.save_and_reraise_exception():
              msg = "timeout on netconf recv, msg received so far: %s" % responses
              LOG.error(msg)

    @lockutils.synchronized(kconst.SESSION_INIT_LOCK, external=True)
    def _init_netconf_session(self):
        transport = self.client.get_transport()
        if transport is not None and transport.is_active():
            return
        #create a session/chan, reset msg_id, reset receiver thread 
        self.msgid = 0
        # stop receiver thread
        if self.receiver.is_running():
           self.receiver.stop()
           self.receiver.wait()
           LOG.info("kaloom netconf receiver loop stopped")

        try:
           private_key = paramiko.RSAKey.from_private_key_file(self.private_key_file)
           self.client.connect(self.host, self.port, self.username,
                              pkey = private_key, look_for_keys=False, allow_agent=False, timeout = self.connect_timeout)
        except Exception as e:
           LOG.debug("Error loading kaloom private key %s: %s, fallback to password", self.private_key_file, e )
           try:
              self.client.connect(self.host, self.port, self.username,
                                  self.password, look_for_keys=False, allow_agent=False, timeout = self.connect_timeout)
           except Exception as e:
              raise ValueError("vfabric netconf connect failed msg:%s" %  e)
        self.client.get_transport().set_keepalive(self.keepalive_interval_sec) #session keepalive 
        self.chan = self.client.get_transport().open_session()
        self.chan.invoke_subsystem('netconf')
        self.chan.settimeout(self.timeout_sec) #timeout on blocking read/write operations

        hello_frm_server = self._read() #throws exception

        try:
            msg = objectify.fromstring(hello_frm_server)
            self.netconf_session_id = msg['session-id']
        except Exception as e:
            with excutils.save_and_reraise_exception(): #throws exception
               LOG.error('Error reading session-id from hello message: %s', e)

        LOG.info('netconf session-id %s', self.netconf_session_id)
        LOG.debug(hello_frm_server)
        self.chan.sendall(MESG_HELLO + TERMINATOR)

        #update receiver thread of the chan
        self.receiver.update_chan(self.chan)

        return

    @lockutils.synchronized(kconst.MSGID_LOCK, external=True)
    def _get_next_msgid(self):
        self.msgid = self.msgid + 1
        return self.msgid

    def _exec_netconf_cmd(self, req_xml):
        self._init_netconf_session() #throws exception
        msgid = self._get_next_msgid()
        req_xml = req_xml.replace("message_id", str(msgid))
        #before sending netconf request, notify callback event to be used by receiver thread.
        evt = event.Event() # single event
        self.receiver.add_callback_event(str(msgid), evt)
        #send netconf request
        self.chan.sendall(req_xml + TERMINATOR)
        #block in event, until timeout 
        try: 
           with Timeout(self.timeout_sec):
              response_xml = evt.wait()
        except ValueError as e: #receiver thread on_done sends exception, stop waiting
            msg = "Error on netconf reply recv for session-id %s msgid %s errmsg:%s" % (self.netconf_session_id, msgid, e)
            LOG.error(msg)
            raise ValueError(msg)
        except Timeout: #Timeout
            msg = "timeout on netconf reply recv for session-id %s msgid %s" % (self.netconf_session_id, msgid)
            LOG.error(msg)
            self.receiver.del_callback_event(str(msgid))
            raise ValueError(msg)

        xml_obj = xml.dom.minidom.parseString(response_xml)
        pretty_xml = xml_obj.toprettyxml()
        LOG.debug(pretty_xml)
        return pretty_xml

    def _edit_config_req(self, subtree):
        edit_config_req = """
            <?xml version="1.0" encoding="UTF-8"?>
            <rpc xmlns="urn:ietf:params:xml:ns:netconf:base:1.0" message-id="message_id">
              <edit-config>
                <target>
                  <running />
                </target>
                <default-operation>none</default-operation>
                <config>
                    %s
                </config>
              </edit-config>
            </rpc> """ % (subtree)
        return edit_config_req

    def _filter_req(self, subtree):
        filter_req = """
            <?xml version="1.0" encoding="UTF-8"?>
            <rpc message-id="message_id" xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
            <get>
              <filter xmlns:ns0="urn:ietf:params:xml:ns:netconf:base:1.0" ns0:type="subtree">
              %s
              </filter>
            </get>
            </rpc> """ % (subtree)
        return filter_req

    def _get_l2_network(self, subtree):
        get_nw_req = """
            <networks xmlns="urn:ietf:params:xml:ns:yang:ietf-network">
              <network>
              <network-id>2</network-id>
              %s
              </network>
              </networks>
        """ % (subtree)

        return self._filter_req(get_nw_req)

    def get_l2_network_by_name(self, nw_name):
        nw_name_subtree = """
        <node>
        <node-id>%s</node-id>
        <l2-node-attributes xmlns="urn:ietf:params:xml:ns:yang:ietf-l2-topology">
           <KNID xmlns="urn:kaloom:faas:vfabric-l2-topology"/>
        </l2-node-attributes>
        </node>
        """ % (nw_name)

        req = self._get_l2_network(nw_name_subtree)
        LOG.debug(req)

        resp = self._exec_netconf_cmd(req)
        LOG.debug(resp)

        nw_xml_root = objectify.fromstring(resp).getroottree()
        nw = nw_xml_root.find('//' + TAG_L2_NODE_ATTR)
        if nw is not None:
           kaloom_knid = nw.find(TAG_NW_ATTR_KNID)
           return {'kaloom_knid': int(kaloom_knid)}
        return None

    def get_l2_network_names(self, prefix):
        nw_name_subtree = """
        <node>
        <node-id/>
        </node>
        """
        req = self._get_l2_network(nw_name_subtree)
        LOG.debug(req)

        resp = self._exec_netconf_cmd(req)
        LOG.debug(resp)

        nw_xml_root = objectify.fromstring(resp).getroottree()
        networks = nw_xml_root.findall('//' + TAG_NODE_ID)
        nw_names=[]
        for nw in networks:
            name = nw.text
            if name.startswith(prefix):
               nw_names.append(name)
        return nw_names

    def get_tp_by_annotation(self, host):
        _KEY = "OpenStack_OVS_Host"
        tp_req = """
        <top xmlns:nw="%(nw)s"
           xmlns:nt="%(nt)s"
           xmlns:vf="%(vf)s">
           <nw:networks>
             <nw:network>
               <nw:network-id>1</nw:network-id>
                 <nw:node>
                   <nt:termination-point>
                     <vf:annotations>
                       <vf:the-key>%(key)s</vf:the-key>
                       <vf:value>%(host)s</vf:value>
                     </vf:annotations>
                   </nt:termination-point>
                 </nw:node>
             </nw:network>
           </nw:networks>
        </top>
        """ % {'nw': NW_NS , 'nt': NT_NS, 'vf':VF_NS , 'key':_KEY, 'host': host}

        req = self._filter_req(tp_req)
        LOG.debug(req)

        resp = self._exec_netconf_cmd(req)
        LOG.debug(resp)

        tp_xml_root = objectify.fromstring(resp).getroottree()
        tps = tp_xml_root.findall('//' + TAG_TP_ATTR)
        for tp in tps:
            tpid = tp.find(TAG_TP_ID)
            annotations = tp.findall(TAG_VF_ANNOTATIONS)
            for annotation in annotations: 
                 key = annotation.find(TAG_VF_KEY)
                 value = annotation.find(TAG_VF_VALUE)
                 if key == _KEY and value == host:
                    return {'name': host, 'id': tpid}
        return None

    def create_l2_network(self, nw_name, gui_nw_name, default_vlanid):
        l2_create_req = """<networks xmlns="urn:ietf:params:xml:ns:yang:ietf-network">
              <network>
                <network-id>2</network-id>
                <node xmlns:a="urn:ietf:params:xml:ns:netconf:base:1.0" a:operation="create">
                  <node-id>%(name)s</node-id>
                  <vl2-neighbors xmlns="urn:kaloom:faas:vfabric-l2-topology">
                    <arp-suppression-enable>false</arp-suppression-enable>
                    <nd-suppression-enable>false</nd-suppression-enable>
                  </vl2-neighbors>
                  <vl2-mac xmlns="urn:kaloom:faas:vfabric-l2-topology">
                    <mac-address-table-aging-enable>false</mac-address-table-aging-enable>
                  </vl2-mac>
                  <l2-node-attributes xmlns="urn:ietf:params:xml:ns:yang:ietf-l2-topology">
                    <name>%(gui_name)s</name>
                    <description>%(gui_name)s</description>
                  </l2-node-attributes>
                </node></network></networks>""" % {'name': nw_name,'gui_name': gui_nw_name}

        req = self._edit_config_req(l2_create_req)
        resp = self._exec_netconf_cmd(req)

        LOG.debug(resp)
        self._validate_response(resp)

        return self.get_l2_network_by_name(nw_name)

    def rename_l2_network(self, nw_name, gui_nw_name):
        l2_rename_req = """<networks xmlns="urn:ietf:params:xml:ns:yang:ietf-network">
              <network>
                <network-id>2</network-id>
                <node>
                  <node-id>%(nw_name)s</node-id>
                  <l2-node-attributes xmlns="urn:ietf:params:xml:ns:yang:ietf-l2-topology" xmlns:a="urn:ietf:params:xml:ns:netconf:base:1.0" a:operation="merge">
                    <name>%(gui_nw_name)s</name>
                    <description>%(gui_nw_name)s</description>
                  </l2-node-attributes>
                </node></network></networks>""" % {'nw_name':nw_name, 'gui_nw_name': gui_nw_name}

        req = self._edit_config_req(l2_rename_req)
        resp = self._exec_netconf_cmd(req)

        LOG.debug(resp)
        self._validate_response(resp)

    def delete_l2_network(self, nw_name):
        l2_delete_req = """
        <networks xmlns="urn:ietf:params:xml:ns:yang:ietf-network">
        <network>
        <network-id>2</network-id>
        <node xmlns:a="urn:ietf:params:xml:ns:netconf:base:1.0" a:operation="remove">
        <node-id>%s</node-id>
        </node>
        </network>
        </networks>""" % (nw_name)

        req = self._edit_config_req(l2_delete_req)
        resp = self._exec_netconf_cmd(req)

        LOG.debug(resp)
        self._validate_response(resp)

    def attach_tp_to_l2_network(self, nw_name, attach_name, tpid, vlan_id):
        attach_req = """
           <networks xmlns="urn:ietf:params:xml:ns:yang:ietf-network">
           <network>
           <network-id>2</network-id>
           <node>
           <node-id>%(nw_name)s</node-id>
           <termination-point xmlns="urn:ietf:params:xml:ns:yang:ietf-network-topology" xmlns:a="urn:ietf:params:xml:ns:netconf:base:1.0" a:operation="create">
           <tp-id>%(tpid)s</tp-id>
           <l2-termination-point-attributes xmlns="urn:ietf:params:xml:ns:yang:ietf-l2-topology">
           <description>%(name)s</description>
           <encapsulation-type xmlns="urn:kaloom:faas:vfabric-l2-topology">VLAN</encapsulation-type>
           <vlan-id xmlns="urn:kaloom:faas:vfabric-l2-topology">%(vlan_id)d</vlan-id>
           </l2-termination-point-attributes>
           <name xmlns="urn:kaloom:faas:vfabric-l2-topology">%(name)s</name>
           </termination-point>
           </node>
           </network>
           </networks>""" % {"name": attach_name, "nw_name": nw_name, "tpid": tpid, "vlan_id": vlan_id}

        req = self._edit_config_req(attach_req)
        resp = self._exec_netconf_cmd(req)
        self._validate_response(resp)

        LOG.debug(resp)

    def detach_tp_from_l2_network(self, nw_name, tpid):
        detach_req = """
        <networks xmlns="urn:ietf:params:xml:ns:yang:ietf-network">
        <network>
        <network-id>2</network-id>
        <node>
        <node-id>%s</node-id>
        <termination-point xmlns="urn:ietf:params:xml:ns:yang:ietf-network-topology" xmlns:a="urn:ietf:params:xml:ns:netconf:base:1.0" a:operation="remove">
        <tp-id>%s</tp-id>
        </termination-point>
        </node>
        </network>
        </networks>
        """ % (nw_name, tpid)

        req = self._edit_config_req(detach_req)
        resp = self._exec_netconf_cmd(req)

        LOG.debug(resp)
        self._validate_response(resp)

    def _validate_response(self, resp):
        resp_xml = objectify.fromstring(resp)
        try:
            if resp_xml['ok']:
                return
        except AttributeError:
            LOG.warning('session-id: %s, msg-reply: %s', self.netconf_session_id, resp)
            raise ValueError(resp_xml['rpc-error']['error-message'])

    def list_router_name_id(self):
        req = L3_command_dict["LIST_ROUTER"]
        resp = self._exec_netconf_cmd(req)

        LOG.debug(resp)
        xml_root = objectify.fromstring(resp).getroottree()
        nodes = xml_root.findall('//' + TAG_NODE)
        routers=[]
        for node in nodes:
            node_attr = node.find(TAG_L3_ATTR)
            name = node_attr.find(TAG_L3_NAME).text
            node_id = node.find(TAG_NODE_ID).text
            routers.append((name,node_id))
        return routers

    def get_router_id_by_name(self, router_name):
        req = L3_command_dict["GET_ROUTER_ID"] % {'name':router_name}
        resp = self._exec_netconf_cmd(req)

        LOG.debug(resp)
        xml_root = objectify.fromstring(resp).getroottree()
        id = xml_root.find('//' + TAG_NODE_ID)
        if id is None:
            return None
        return id.text

    def get_router_interface_info(self, router_name, l2_node_id):
        req = L3_command_dict["GET_ROUTER_INTERFACE_INFO"] % {'router_name': router_name}
        resp = self._exec_netconf_cmd(req)
        LOG.debug(resp)
        router_inf_info={'node_id': None, 'interface': None, 'ip_addresses': []}

        xml_root = objectify.fromstring(resp).getroottree()
        node = xml_root.find('//' + TAG_NODE)
        if node is None:
           return router_inf_info
        router_inf_info['node_id'] = node.find(TAG_NODE_ID).text
        nt_tps = node.findall(TAG_NT_TP)
        #find router_interface connecting to l2_node, if any
        for nt_tp in nt_tps:
           supporting_tp = nt_tp.find(TAG_NT_SUPPORTING_TP)
           supporting_node_layer = supporting_tp.find(TAG_NT_NETWORK_REF).text
           supporting_node_id = supporting_tp.find(TAG_NT_NODE_REF).text
           if supporting_node_layer == '2' and supporting_node_id == l2_node_id:
              router_inf_info['interface'] = nt_tp.find(TAG_L3T_L3_TP_ATTR).find(TAG_VL3T_IFNAME).text
              break
        #now find IPs for the router_interface
        if router_inf_info['interface']:  
           interfaces = node.find(TAG_VIF_INTERFACES).findall(TAG_VIF_INTERFACE)
           for interface in interfaces:
              if router_inf_info['interface'] == interface.find(TAG_VIF_NAME).text:
                interface_ipv4_addresses = interface.find(TAG_VIP_IPV4).findall(TAG_VIP_ADDRESS)
                interface_ipv6_addresses = interface.find(TAG_VIP_IPV6).findall(TAG_VIP_ADDRESS)
                for address in interface_ipv4_addresses + interface_ipv6_addresses:
                  ip = address.find(TAG_VIP_IP).text
                  router_inf_info['ip_addresses'].append(ip)
                break
        return router_inf_info

    def create_router(self, router_name):
        req = L3_command_dict["CREATE_ROUTER"] % {'router_name':router_name}
        resp = self._exec_netconf_cmd(req)

        LOG.debug(resp)
        resp_xml = objectify.fromstring(resp)
        xml_root = resp_xml.getroottree()
        node_id = xml_root.find(TAG_L3_NODE_ID)
        if node_id is None:
            raise ValueError(resp_xml['rpc-error']['error-message'])

    def rename_router(self, router_info):
        req = L3_command_dict["RENAME_ROUTER"] % {'router_node_id':router_info['router_node_id'], 'router_name':router_info['router_name']}
        resp = self._exec_netconf_cmd(req)

        LOG.debug(resp)
        self._validate_response(resp)   ##raise ValueError

    def delete_router(self, router_node_id):
        req = L3_command_dict["DELETE_ROUTER"] % {'router_node_id':router_node_id}
        resp = self._exec_netconf_cmd(req)

        LOG.debug(resp)
        self._validate_response(resp)   ##raise ValueError

    def attach_router(self, router_node_id, l2_node_id):
        req = L3_command_dict["ATTACH_ROUTER"] % {'router_node_id':router_node_id, 'l2_node_id':l2_node_id}
        resp = self._exec_netconf_cmd(req)

        LOG.debug(resp)
        resp_xml = objectify.fromstring(resp)
        xml_root = resp_xml.getroottree()
        tp_interface = xml_root.find(TAG_L3_INTERFACE_NAME)
        if tp_interface is None:
            raise ValueError(resp_xml['rpc-error']['error-message'])
        else:
            return tp_interface.text

    def detach_router(self, router_node_id, l2_node_id):
        req = L3_command_dict["DETACH_ROUTER"] % {'router_node_id':router_node_id, 'l2_node_id':l2_node_id}
        resp = self._exec_netconf_cmd(req)

        LOG.debug(resp)
        self._validate_response(resp)   ##raise ValueError

    def add_ipaddress_to_interface(self, router_info):
        if router_info['ip_version'] == 4:
            req = L3_command_dict["addIPv4AddressToInterface"]
        else:
            req = L3_command_dict["addIPv6AddressToInterface"]
        req = req % {'router_node_id':router_info['router_node_id'], 'interface_name':router_info['interface_name'], 'ip_address':router_info['ip_address'], 'prefix_length':router_info['prefix_length']}
        resp = self._exec_netconf_cmd(req)

        LOG.debug(resp)
        self._validate_response(resp)   ##raise ValueError

    def delete_ipaddress_from_interface(self, router_info):
        if router_info['ip_version'] == 4:
            req = L3_command_dict["deleteIPv4AddressFromInterface"]
        else:
            req = L3_command_dict["deleteIPv6AddressFromInterface"]
        req = req % {'router_node_id':router_info['router_node_id'], 'interface_name':router_info['interface_name'], 'ip_address':router_info['ip_address']}
        resp = self._exec_netconf_cmd(req)

        LOG.debug(resp)
        self._validate_response(resp)   ##raise ValueError

    def add_ip_static_route(self, route_info):
        if route_info['ip_version'] == 4:
            req = L3_command_dict["addIPv4StaticRoute"]
        else:
            req = L3_command_dict["addIPv6StaticRoute"]
        req = req % {'router_node_id': route_info['router_node_id'], 'destination_prefix':route_info['destination_prefix'], 'next_hop_address':route_info['next_hop_address']}
        resp = self._exec_netconf_cmd(req)

        LOG.debug(resp)
        self._validate_response(resp)   ##raise ValueError

    def delete_ip_static_route(self, route_info):
        if route_info['ip_version'] == 4:
            req = L3_command_dict["deleteIPv4StaticRoute"]
        else:
            req = L3_command_dict["deleteIPv6StaticRoute"]
        req = req % {'router_node_id':route_info['router_node_id'], 'destination_prefix':route_info['destination_prefix']}
        resp = self._exec_netconf_cmd(req)

        LOG.debug(resp)
        self._validate_response(resp)   ##raise ValueError

if __name__ == "__main__":
    from eventlet import monkey_patch
    monkey_patch()
    host = "xx.xx.xx.xx"
    port = 830
    username = "admin"
    private_key_file = ""
    password = "kaloom355"

    kn = KaloomNetconf(host, port, username, private_key_file, password)
    print kn.get_l2_network_names("__OpenStack__")
