=======================
Neutron Server Features
=======================

Neutron Server Plugin provides the following enhanced networking features:

* Creation of L2 and L3 networks on demand for OpenStack VM connectivity
* Accelerated flow distribution performance between directly connected OpenStack KVS compute nodes to the Kaloom SDF


*L2 networks*
=============

   networks
     This feature adds/creates the L2/L3 Normalized network. The KNID type is configured by updating the network_type field to kaloom_knid (e.g. provider-network-type = kaloom_knid)."

   address scope
     This feature controls where addresses from subnet pools can be routed between networks, preventing the use of overlapping addresses in any two subnets.  

   dns integration
     This feature uses the default implementation using dnsmasq or other existing DHCP service

   external
     The external feature integrates the use of external and knid network types 

   multiple provider
     The multi-provider extension feature allows administrative users to define multiple physical bindings for a logical network. The multiple provider field value is configured by using the same network range label (e.g. provider) and assigning it to different network types. (e.g. provider:network_type, provider:physical_network, and provider:segmentation_id).
   
   provider extended attribute
     The provider extended attribute feature for networks enable administrative users to specify the network objects mapping to the underlying networking infrastructure (l2 flat network, VLAN, VXLAN, etc.).

   vlan transparency
     The VLAN transparency feature is implemented through KVS by default (kff:attach port raw)

*Ports*
======= 

   port bindings
      The port binding feature is implemented by setting the following optional binding label values: binding:host_id, binding:vnic_type, binding:vif_type, binding:vif_details, and binding:profile

*L3 networks*
=============

   vRouter
     BGP routing  

