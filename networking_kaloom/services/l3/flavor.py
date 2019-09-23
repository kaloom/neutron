# Copyright 2019 Kaloom, Inc.  All rights reserved.
# Copyright 2018 Intel Corporation.
# Copyright 2018 Isaku Yamahata <isaku.yamahata at intel com>
#                               <isaku.yamahata at gmail com>
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

from neutron.objects import router as l3_obj
from neutron.services.l3_router.service_providers import base
from neutron_lib.callbacks import events
from neutron_lib.callbacks import registry
from neutron_lib.callbacks import resources
from neutron_lib.plugins import constants as plugin_constants
from neutron_lib.plugins import directory
from oslo_log import helpers as log_helpers
from oslo_log import log as logging

from networking_kaloom.services.l3 import driver as kaloom_l3_driver

LOG = logging.getLogger(__name__)


@registry.has_registry_receivers
class KaloomL3ServiceProvider(base.L3ServiceProvider):
    @log_helpers.log_method_call
    def __init__(self, l3_plugin):
        super(KaloomL3ServiceProvider, self).__init__(l3_plugin)
        self.kaloom_provider = __name__ + "." + self.__class__.__name__
        self.prefix = '__OpenStack__'
        self.driver = kaloom_l3_driver.KaloomL3Driver(self.prefix)

    @property
    def _flavor_plugin(self):
        try:
            return self._flavor_plugin_ref
        except AttributeError:
            self._flavor_plugin_ref = directory.get_plugin(
                plugin_constants.FLAVORS)
            return self._flavor_plugin_ref

    def _validate_l3_flavor(self, context, flavor_id):
        if flavor_id is None:
            return False
        provider = self._flavor_plugin.get_flavor_next_provider(
            context, flavor_id)[0]
        return str(provider['driver']) == self.kaloom_provider


    @registry.receives(resources.ROUTER, [events.AFTER_CREATE])
    @log_helpers.log_method_call
    def _router_create_postcommit(self, resource, event, trigger, **kwargs):
        context = kwargs['context']
        router_dict = kwargs['router']
        flavor_id = router_dict['flavor_id']

        if not self._validate_l3_flavor(context, flavor_id):
            return

        # create router on the vFabric
        self.driver.create_router(context, router_dict)

    @registry.receives(resources.ROUTER, [events.AFTER_DELETE])
    @log_helpers.log_method_call
    def _router_delete_postcommit(self, resource, event, trigger, **kwargs):
        context = kwargs['context']
        router_id = kwargs['router_id']
        router_dict = kwargs['original']
        flavor_id = router_dict['flavor_id']
        if not self._validate_l3_flavor(context, flavor_id):
            return

        # Delete router on the Kaloom vFabic
        self.driver.delete_router(context, router_id, router_dict)


    @registry.receives(resources.ROUTER, [events.AFTER_UPDATE])
    @log_helpers.log_method_call
    def _router_update_postcommit(self, resource, event, trigger, **kwargs):
        LOG.info("router update: %s", kwargs)

    @registry.receives(resources.ROUTER_GATEWAY, [events.AFTER_CREATE])
    @log_helpers.log_method_call
    def _router_gateway_interface_create_postcommit(self, resource, event, trigger, **kwargs):
        LOG.info("router_gateway_interface_create: %s", kwargs)

    @registry.receives(resources.ROUTER_INTERFACE, [events.AFTER_CREATE])
    @log_helpers.log_method_call
    def _router_interface_create_postcommit(self, resource, event, trigger, **kwargs):
        LOG.info("router_interface_create: %s", kwargs)

    @registry.receives(resources.ROUTER_GATEWAY, [events.AFTER_DELETE])
    @log_helpers.log_method_call
    def _router_gateway_interface_delete_postcommit(self, resource, event, trigger, **kwargs):
        LOG.info("router_gateway_interface_delete: %s", kwargs)

    @registry.receives(resources.ROUTER_INTERFACE, [events.AFTER_DELETE])
    @log_helpers.log_method_call
    def _router_interface_delete_postcommit(self, resource, event, trigger, **kwargs):
        LOG.info("router_interface_delete: %s", kwargs)

