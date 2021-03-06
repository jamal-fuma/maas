# Copyright 2015-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""API handlers: `Fan Network`."""

from maasserver.api.support import (
    admin_method,
    OperationsHandler,
)
from maasserver.exceptions import MAASAPIValidationError
from maasserver.forms.fannetwork import FanNetworkForm
from maasserver.models import FanNetwork
from maasserver.permissions import NodePermission
from piston3.utils import rc


DISPLAYED_FANNETWORK_FIELDS = (
    'id',
    'name',
    'underlay',
    'overlay',
    'dhcp',
    'host_reserve',
    'bridge',
    'off',
)


class FanNetworksHandler(OperationsHandler):
    """Manage Fan Networks."""
    api_doc_section_name = "Fan Networks"
    update = delete = None
    fields = DISPLAYED_FANNETWORK_FIELDS

    @classmethod
    def resource_uri(cls, *args, **kwargs):
        # See the comment in NodeHandler.resource_uri.
        return ('fannetworks_handler', [])

    def read(self, request):
        """List all fannetworks."""
        return FanNetwork.objects.all()

    @admin_method
    def create(self, request):
        """Create a fannetwork.

        :param name: Name of the fannetwork.
        :param overlay: Overlay network
        :param underlay: Underlay network
        :param dhcp: confiugre dhcp server for overlay net
        :param host_reserve: number of IP addresses to reserve for host
        :param bridge: override bridge name
        :param off: put this int he config, but disable it.
        """
        form = FanNetworkForm(data=request.data)
        if form.is_valid():
            return form.save()
        else:
            raise MAASAPIValidationError(form.errors)


class FanNetworkHandler(OperationsHandler):
    """Manage Fan Network."""
    api_doc_section_name = "Fan Network"
    create = None
    model = FanNetwork
    fields = DISPLAYED_FANNETWORK_FIELDS

    @classmethod
    def resource_uri(cls, fannetwork=None):
        # See the comment in NodeHandler.resource_uri.
        fannetwork_id = "id"
        if fannetwork is not None:
            fannetwork_id = fannetwork.id
        return ('fannetwork_handler', (fannetwork_id,))

    def read(self, request, id):
        """Read fannetwork.

        Returns 404 if the fannetwork is not found.
        """
        return FanNetwork.objects.get_fannetwork_or_404(
            id, request.user, NodePermission.view)

    def update(self, request, id):
        """Update fannetwork.

        :param name: Name of the fannetwork.
        :param overlay: Overlay network
        :param underlay: Underlay network
        :param dhcp: confiugre dhcp server for overlay net
        :param host_reserve: number of IP addresses to reserve for host
        :param bridge: override bridge name
        :param off: put this int he config, but disable it.

        Returns 404 if the fannetwork is not found.
        """
        fannetwork = FanNetwork.objects.get_fannetwork_or_404(
            id, request.user, NodePermission.admin)
        form = FanNetworkForm(instance=fannetwork, data=request.data)
        if form.is_valid():
            return form.save()
        else:
            raise MAASAPIValidationError(form.errors)

    def delete(self, request, id):
        """Delete fannetwork.

        Returns 404 if the fannetwork is not found.
        """
        fannetwork = FanNetwork.objects.get_fannetwork_or_404(
            id, request.user, NodePermission.admin)
        fannetwork.delete()
        return rc.DELETED
