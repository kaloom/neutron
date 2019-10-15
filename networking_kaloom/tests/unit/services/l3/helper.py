from string import lower
from oslo_utils import uuidutils
from oslo_db.sqlalchemy import enginefacade

from neutron_lib.services import base as service_base
from neutron.db import extraroute_db
from neutron.db import l3_gwmode_db
from neutron.db import l3_agentschedulers_db
from neutron.db.migration import cli as migration_cli
from neutron.db import ipam_pluggable_backend
from neutron_lib import constants as n_const

class SubstringMatcher():
    def __init__(self, containing):
        self.containing = lower(containing)
    def __eq__(self, other):
        return lower(other).find(self.containing) > -1
    def __unicode__(self):
        return 'a string containing "%s"' % self.containing
    def __str__(self):
        return unicode(self).encode('utf-8')
    __repr__=__unicode__

class MockParent(service_base.ServicePluginBase,
                            extraroute_db.ExtraRoute_db_mixin,
                            l3_gwmode_db.L3_NAT_db_mixin,
                            l3_agentschedulers_db.L3AgentSchedulerDbMixin):
    def __init__(self):
        super(MockParent, self).__init__()

    #mock methods
    def add_worker(self, MagicMock):
        pass

    def notify_router_deleted(self, context, id):
        pass

def get_mock_router_kwargs():
    from mock import Mock
    router_db = Mock(gw_port_id=uuidutils.generate_uuid(),
                            id=uuidutils.generate_uuid())
    router = {'router':
                {'name': 'router1',
                'admin_state_up': True,
                'tenant_id': uuidutils.generate_uuid(),
                'flavor_id': uuidutils.generate_uuid(),
                'id': router_db.id,
                },
                }
    return router

def get_context_manager(url):
    _CTX_MANAGER = enginefacade._TransactionContextManager(connection=url)
    _CTX_MANAGER.configure(sqlite_fk=True, flush_on_subtransaction=True)
    return _CTX_MANAGER

#neutron.db.db_base_plugin_common.DbBasePluginCommon's method without wrapper "@db_api.context_manager.writer", to avoid sqlite
@staticmethod
def _store_ip_allocation(context, ip_address, network_id, subnet_id,
                            port_id):
    from neutron.objects import ports as port_obj
    from oslo_log import log as logging
    LOG = logging.getLogger(__name__)
    LOG.debug("Allocated IP %(ip_address)s "
                "(%(network_id)s/%(subnet_id)s/%(port_id)s)",
                {'ip_address': ip_address,
                'network_id': network_id,
                'subnet_id': subnet_id,
                'port_id': port_id})
    allocated = port_obj.IPAllocation(
        context, network_id=network_id, port_id=port_id,
        ip_address=ip_address, subnet_id=subnet_id)
    allocated.create()


def upgrade(alembic_cfg, branch_name='heads'):
    migration_cli.do_alembic_command(alembic_cfg, 'upgrade', branch_name)

def _create_network(self):
    net = self.l2_plugin.create_network(
        self.ctx,
        {'network': {'name': 'name',
                        'tenant_id': 'tenant_one',
                        'shared': False,
                        'admin_state_up': True,
                        'status': 'ACTIVE' }})
    return net['id']

def _create_network_ext(self):
    #fix _validate_gw_info to mock network as external
    def _get_network(context, network_id):
        from neutron.db.models_v2 import Network
        network_db = original__get_network(context, network_id)
        Network.external = property(lambda self: True)
        return network_db

    original__get_network = self.l2_plugin._get_network
    self.l2_plugin._get_network = _get_network
    return _create_network(self)

def _create_segment(self, network_id):
    seg = self.segments_plugin.create_segment(
        self.ctx,
        {'segment': {'network_id': network_id,
                        'name': None, 'description': None,
                        'physical_network': 'physnet1',
                        'network_type': 'vlan',
                        'segmentation_id': n_const.ATTR_NOT_SPECIFIED}})
    return seg['id']

def _create_subnet(self, segment_id, network_id, cidr='192.168.10.0/24'):
    #ipam_pluggable_backend.IpamPluggableBackend's method without wrapper "@db_api.context_manager.writer", to avoid sqlite
    def save_allocation_pools(self, context, subnet, allocation_pools):
        import netaddr
        from neutron.objects import subnet as obj_subnet
        for pool in allocation_pools:
            first_ip = str(netaddr.IPAddress(pool.first, pool.version))
            last_ip = str(netaddr.IPAddress(pool.last, pool.version))
            obj_subnet.IPAllocationPool(
                context, subnet_id=subnet['id'], start=first_ip,
                end=last_ip).create()

    ipam_pluggable_backend.IpamPluggableBackend.save_allocation_pools = save_allocation_pools
    subnet = self.l2_plugin.create_subnet(
        self.ctx,
        {'subnet': {'name': 'name',
                    'ip_version': 4,
                    'network_id': network_id,
                    'cidr': cidr,
                    'gateway_ip': n_const.ATTR_NOT_SPECIFIED,
                    'allocation_pools': n_const.ATTR_NOT_SPECIFIED,
                    'dns_nameservers': n_const.ATTR_NOT_SPECIFIED,
                    'host_routes': n_const.ATTR_NOT_SPECIFIED,
                    'tenant_id': 'tenant_one',
                    'enable_dhcp': True,
                    'segment_id': segment_id}})
    return subnet['id']

