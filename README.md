<!---
 Copyright 2019 Kaloom, Inc.  All rights reserved.
    Licensed under the Apache License, Version 2.0 (the "License"); you may
    not use this file except in compliance with the License. You may obtain
    a copy of the License at

         http://www.apache.org/licenses/LICENSE-2.0

    Unless required by applicable law or agreed to in writing, software
    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
    License for the specific language governing permissions and limitations
    under the License.
 --->

# Kaloom Neutron ML2 Plugin

### Building and Development

Clone the repo

```bash
$ git clone https://github.com/kaloom/neutron.git
$ ./docker-build.sh
```
To install Kaloom ML2, run

```bash
$ cd neutron
$ cp networking_kaloom-setup.cfg setup.cfg
$ sudo python setup.py install
```

To install KVS L2 agent

Download the src RPM *kaloom_kvs_agent-<version>.src.rpm* and copy them
to the correct location.

```bash
$ cd
$ rpm2cpio kaloom_kvs_agent-<version>.src.rpm | cpio -idmv
$ tar xzvhf kaloom_kvs_agent-<version>.tar.gz
$ cp -R kaloom_kvs_agent-<version>/stub/ ~/neutron/kaloom_kvs_agent/
$ cd neutron
$ cp kaloom_kvs_agent-setup.cfg setup.cfg
$ sudo python setup.py install
```

You can manually run the agent from the command line

```bash
$ sudo neutron-kaloom-agent \
	--config-file /usr/share/neutron/neutron-dist.conf \
	--config-file /etc/neutron/neutron.conf \
	--config-file /etc/neutron/plugins/ml2/ml2_conf_kaloom.ini
```

### Testing

In order to test or troubleshoot one needs to launch the development container in persistent mode:

```bash
$ docker run --rm  -it -v `pwd`:/opt/neutron kaloom/build-neutron:1.0.0 bash
```

Run the tests by executing the following command

```bash
$ cd /opt/neutron
$ nosetests networking_kaloom/tests
```

# Installation
### On The vFabric manager

Make sure that the L1 Termination Point (TP) which is used for the **provider
network** has the key-value annotation: key as "OpenStack_OVS_Host" and value as 
**same name** as the hostname in OpenStack. The plugin uses the TP annotation
to identify which TP is connected to the given host's **provider network**.

We can set the TP annotation using the `setTpAnnotation` utility

```bash
$ ./setTpAnnotation e2053869-a5f6-41b8-9b9b-778ea648c220 \
	r620-40JMCY1.OpenStack.lab.kaloom.io
```

In the above example, `r620-40JMCY1.OpenStack.lab.kaloom.io` is the hostname of 
Openstack server and `e2053869-a5f6-41b8-9b9b-778ea648c220` is the UUID of a TP 
that is connected to the given host's br-provider upstream port.

### On the Controller node
Get the latest `networking_kaloom` RPM package from the releases page and install it on
the controller node.
```bash
$ sudo yum localinstall -y networking_kaloom.rpm
```

### On KVS running node
Get the latest `kaloom_kvs_agent` RPM package from the releases page and install it on 
KVS node
```bash
$ sudo yum install python-pip
$ sudo pip install grpcio grpcio-tools
$ sudo yum localinstall -y  kaloom_kvs_agent.rpm
```

Proceed to the configuration section after the installation and follow the steps

# Configuration
The following sections show different configurations needed on different nodes

## Controller Configuration
1. Create private/public key-pair, for vFabric netconf authentication
```bash
$ mkdir -p /etc/neutron/plugins/ml2/.ssh
$ ssh-keygen -t rsa -f /etc/neutron/plugins/ml2/.ssh/kaloom_netconf
$ chown root:neutron /etc/neutron/plugins/ml2/.ssh/kaloom_netconf
$ chmod 440 /etc/neutron/plugins/ml2/.ssh/kaloom_netconf
```
2. push public-key kaloom_netconf.pub contents to vfabric: via GUI or netconf api 

3. Stop neutron server
```bash
$ sudo systemctl stop neutron-server
```

4. Edit `/etc/neutron/plugins/ml2/ml2_conf.ini` and add the following
   section at the end. Make sure you have the correct values
   for each variable.
```ini
   [KALOOM]
   # Kaloom VFabric controller IP
   kaloom_host=10.201.12.21
   # Kaloom VFabric controller netconf port
   kaloom_port=830
   # Kaloom VFabric controller username
   kaloom_username=admin
   #Kaloom private-key file to authenticate to VFabric Controller
   kaloom_private_key_file = "/etc/neutron/plugins/ml2/.ssh/kaloom_netconf"
   # Kaloom password to authenticate to VFabric controller (as fallback)
   kaloom_password=kaloom355

   ##
   ##For L3 Service plugin
   # Sync interval in seconds between L3 Service plugin and Kaloom vFabric.
   # If not set, a value of 180 seconds is assumed. (integer value)
   # If set to 0, the plugin will never sync after first sync.
   l3_sync_interval = 600
```

5. In `/etc/neutron/plugins/ml2/ml2_conf.ini` update/add the following
   variables
```ini
   mechanism_drivers=kaloom_kvs,kaloom_ovs,openvswitch
   type_drivers=kaloom_knid,vlan,vxlan,flat
   tenant_network_types=kaloom_knid
   [ml2_type_vlan]
   #default VLAN range: 1-4094, if not mentioned.
   network_vlan_ranges = provider
   #pre-provisioned or non-OpenStack-provisioned VLAN (e.g 1-99) can be excluded as:
   #network_vlan_ranges = provider:100:4094 
```

6. In `/etc/neutron/neutron.conf` update/add the following
   variable
```ini
   #use kaloom_l3 instead of router
   service_plugins=qos,kaloom_l3,metering,trunk
```

7. Update the neutron database
```bash
   $ sudo neutron-kaloom-db-manage upgrade head
```

8. Restart neutron server to pick up the changes
```bash
   $ sudo systemctl start neutron-server
```

9. Enable HugePage on Flavour that will be used for VM running on KVS compute node
```bash
   $ sudo su
   $ source /root/keystonerc_admin
   $ openstack flavor create m1.small_hugepage --disk 20 --ram 2048 --property hw:mem_page_size=large
```

10. Once KVS compute nodes are setup, Cleanup down Open vSwitch agents on database.
```bash
    $ sudo su
    $ source /root/keystonerc_admin
    $ openstack network agent list
    $ sudo bash
    # mysql -u root
    mysql> use neutron;
    mysql> delete from agents where id=<id>
```


## OVS Compute Nodes

1. Edit `/etc/neutron/plugins/ml2/openvswitch_agent.ini` 
```ini
   [ovs]
   bridge_mappings = provider:br-provider
```

2. Create the provider bridge
```bash
   $ sudo ovs-vsctl add-br br-provider
   $ sudo ovs-vsctl add-port br-provider PROVIDER_INTERFACE
```

## OVS-DPDK Compute Nodes

1. Increase Hugepage available for VMs
```bash
   $sysctl -w vm.nr_hugepages=4096
```

2. Enable DPDK in OVS
```bash
   $ovs-vsctl --no-wait set Open_vSwitch . other_config:dpdk-init=true
```

3. Edit `/etc/libvirt/qemu.conf` to grant access to vhost-user sockets.
```ini
   group = "hugetlbfs"
```

4. Restart services
```bash
   $systemctl restart openvswitch
   $systemctl restart libvirtd
```

5. Create the provider bridge
```bash
   $ ovs-vsctl add-br br-provider -- set bridge br-provider datapath_type=netdev
```

6. Add dpdk interface to provider bridge
```bash
   $modprobe vfio-pci
   $ifdown p3p1
   $dpdk-devbind -b vfio-pci 0000:04:00.0
   $ovs-vsctl add-port br-provider p3p1 -- set Interface p3p1 type=dpdk options:dpdk-devargs=0000:04:00.0
``` 

7. Edit `/etc/neutron/plugins/ml2/openvswitch_agent.ini`
```ini
   [ovs]
   bridge_mappings = provider:br-provider
   datapath_type = netdev
   vhostuser_socket_dir = /tmp
```

8. Restart service
```bash
   $systemctl restart neutron-openvswitch-agent
```

## KVS Compute Nodes

1. Make sure that KVS is configured and running.
```bash
   $ sudo /opt/kaloom/bin/kvsctl port list
```

2. Increase Hugepage available for VMs
```bash
   $ sudo sysctl -w vm.nr_hugepages=4096
```

3. Install `kaloom_kvs_agent` package on the compute node, edit `/etc/nova/nova.conf` 
```ini
compute_driver=libvirt_kaloom.LibvirtDriverKaloom
```
and restart nova-compute.
```bash
   $ sudo systemctl restart openstack-nova-compute
```

4. Stop Open vSwitch agent if already running
```bash
    $ sudo systemctl stop neutron-openvswitch-agent
    $ sudo systemctl disable neutron-openvswitch-agent
```

5. Do following in case of change in default setting of `vhostuser_socket_dir` in `/etc/neutron/plugins/ml2/ml2_conf_kaloom.ini`
```bash
   $ DIR="/test"
   $ USER=`python -c "from kaloom_kvs_agent.common import utils; print utils.get_qemu_process_user()"`
   $ mkdir $DIR
   $ chown $USER:$USER $DIR
   $ chmod 500 $DIR
   $ semanage fcontext -a -t virt_cache_t "$DIR(/.*)?"
   $ restorecon -Rv $DIR
```

6. Start the Kaloom agent
```bash
   $ sudo systemctl start neutron-kaloom-agent
   $ sudo systemctl enable neutron-kaloom-agent
```

7. Agent LOG can be checked as:
```bash
   $ tail -f /var/log/neutron/neutron-kaloom-agent.log
```

## On the UI (Horizon)

1. Open the file `/usr/share/openstack-dashboard/openstack_dashboard
   /local/local_settings.py` 
   on the Controller node and update the following config
```python
   OPENSTACK_NEUTRON_NETWORK = {
      'extra_provider_types':  {
          'kaloom_knid': {
                  'display_name': 'Kaloom',
                  'require_physical_network': False,
                  'require_segmentation_id': False,
          },
      },
      'supported_provider_types': ['vlan', 'vxlan', 'kaloom_knid']
      ...
   }
```

2. Restart Apache server
```bash
   $ sudo systemctl restart httpd
```

## OVS Network Nodes
1. In case of `service_plugins=router,..` in `/etc/neutron/neutron.conf`, do following
Edit /etc/neutron/l3_agent.ini and update
```ini
   interface_driver = neutron.agent.linux.interface.OVSInterfaceDriver
   #external_network_bridge =
   #gateway_external_network_id = 
```

Restart L3 agent
```bash
   $ systemctl restart neutron-l3-agent
```

2. In case of `service_plugins=kaloom_l3,..` in `/etc/neutron/neutron.conf`
```bash
   $systemctl stop neutron-l3-agent
   $systemctl disable neutron-l3-agent
```
3. Edit `/etc/neutron/dhcp_agent.ini` and update
```bash
    force_metadata = True
```

4. Restart DHCP agent
```bash
   $ sudo systemctl restart neutron-dhcp-agent
```

## KVS Network Nodes
1. In case of `service_plugins=router,..` in `/etc/neutron/neutron.conf`, do following:
Edit /etc/neutron/l3_agent.ini and update
```ini
   interface_driver = kaloom_kvs_agent.interface.KVSInterfaceDriver
   #external_network_bridge =
   #gateway_external_network_id = 
```

Restart L3 agent
```bash
   $ systemctl restart neutron-l3-agent
```

2. In case of `service_plugins=kaloom_l3,..` in `/etc/neutron/neutron.conf`
```bash
   $systemctl stop neutron-l3-agent
   $systemctl disable neutron-l3-agent
```

3. Edit `/etc/neutron/dhcp_agent.ini` and update
```bash
    interface_driver = kaloom_kvs_agent.interface.KVSInterfaceDriver
    force_metadata = True 
```

4. Restart DHCP agent
```bash
   $ sudo systemctl restart neutron-dhcp-agent
```

# Test Operations
The following sections show different CLI commands. 
The Neutron ROUTER\_NAME should follow the regex pattern `(([a-zA-Z0-9_]([a-zA-Z0-9\-_]){0,61})?[a-zA-Z0-9]\.?)|.`.
The Router will appear in vFabric with prefix `__OpenStack__UUID.` to get distinguished from other non-OpenStack-routers and for syncing/cleanup purpose.
vDCO should not use `__OpenStack__` prefix to their non-OpenStack-routers. 
```bash
##External network and subnet
$ export GATEWAY_NET_NAME=gateway_net
$ export GATEWAY_SUBNET_NAME=gateway_sub_net
$ openstack network create --provider-network-type kaloom_knid --provider-physical-network provider --share --external $GATEWAY_NET_NAME 
$ openstack subnet create $GATEWAY_SUBNET_NAME --network $GATEWAY_NET_NAME  --no-dhcp --subnet-range 192.168.10.0/24 --gateway 192.168.10.1 --allocation-pool start=192.168.10.2,end=192.168.10.24
##
##Internal (Tenant) network and subnet
$ export TENANT_NET_NAME=kaloomnet1
$ export TENANT_SUBNET_NAME=subnet1
$ openstack network create --provider-network-type kaloom_knid --provider-physical-network provider $TENANT_NET_NAME
$ openstack subnet create $TENANT_SUBNET_NAME --network $TENANT_NET_NAME --subnet-range 192.168.2.0/24
##
##create router and attach to external_network and tenant_network
$ export ROUTER_NAME=router1
$ openstack router create $ROUTER_NAME
$ openstack router set $ROUTER_NAME --external-gateway $GATEWAY_NET_NAME --disable-snat #[--fixed-ip subnet=$GATEWAY_SUBNET_NAME,ip-address=192.168.10.2]
$ openstack router add subnet $ROUTER_NAME $TENANT_SUBNET_NAME
##
##For extra-routes tests:
$ openstack router set $ROUTER_NAME --route destination=10.20.30.0/24,gateway=192.168.10.1
$ openstack router set $ROUTER_NAME --route destination=10.20.40.0/24,gateway=192.168.10.1
$ openstack router unset $ROUTER_NAME --route destination=10.20.40.0/24,gateway=192.168.10.1
$ openstack router unset $ROUTER_NAME --route destination=10.20.30.0/24,gateway=192.168.10.1
##
##Configure your External Gateway in same L2-network. Manual steps are needed here##
##
## create VM in tenant network
$ export VM_NAME=vm1
$ export FLAVOR=m1.small
$ /root/nova_boot.sh $FLAVOR os-controller $TENANT_NET_NAME $VM_NAME
## Test router -> ext-gateway connectivity
$ router_ns=$(ip netns list|grep qrouter|cut -d ' ' -f 1)
$ ip netns exec $router_ns ping 192.168.10.1 -c 2  ##pings
#ip netns exec $router_ns ping 8.8.8.8 -c 2
$ ip netns exec $router_ns iptables -L -t nat -n -v  # shows SNAT, DNAT rules.. 
##
## Test VM -> ext-gateway connectivity
VM> ping 192.168.10.1  ##pings
#
## Test router -> to VM connectivity
$ VM_IP=$(openstack server list --name $VM_NAME -f value -c Networks| cut -d '=' -f 2)
$ ip netns exec $router_ns ping $VM_IP -c 2  ##100% loss (for OVS controller) (KVS controller does not support SG and allows pings) 
#By default, the default security group applies to all instances and includes firewall rules that deny remote access to instances. 
$ openstack security group rule create --proto icmp default  ##use ID if multiple default
$ openstack security group rule create --proto tcp --dst-port 22 default
$ ip netns exec $router_ns ping $VM_IP -c 2  ##pings
#
## Test ext-gateway to VM connectivity
ip netns exec ext-gateway ping $VM_IP  ##gives "Network is unreachable" #thats expected. 
#
##floating-ip
$ VM_PORT=$(openstack port list --server $VM_NAME -f value -c ID)
$ openstack floating ip create $GATEWAY_NET_NAME --port $VM_PORT  #--fixed-ip-address <ip-address> --floating-ip-address <ip-address>
$ VM_FLOAT_IP=$(openstack floating ip list --port $VM_PORT -f value -c "Floating IP Address")
##ip netns exec $router_ns ip a ##shows floating-ip/32 assigned to interface. 
##ip netns exec $router_ns iptables -L -t nat -n -v  # shows SNAT, DNAT rules per floating ip.
$ ip netns exec ext-gateway ping $VM_FLOAT_IP  ##pings
```
