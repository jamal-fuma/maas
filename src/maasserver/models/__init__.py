# Copyright 2012-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Model export and helpers for maasserver."""

__all__ = [
    'Bcache',
    'BlockDevice',
    'BMC',
    'BMCRoutableRackControllerRelationship',
    'BondInterface',
    'BootResource',
    'BootResourceFile',
    'BootResourceSet',
    'BootSource',
    'BootSourceCache',
    'BootSourceSelection',
    'BridgeInterface',
    'CacheSet',
    'Config',
    'Controller',
    'ControllerInfo',
    'Device',
    'DHCPSnippet',
    'Discovery',
    'DNSData',
    'DNSPublication',
    'DNSResource',
    'Domain',
    'Event',
    'EventType',
    'Fabric',
    'FanNetwork',
    'FileStorage',
    'Filesystem',
    'FilesystemGroup',
    'GlobalDefault',
    'Interface',
    'IPRange',
    'ISCSIBlockDevice',
    'KeySource',
    'LargeFile',
    'LicenseKey',
    'logger',
    'Machine',
    'MDNS',
    'Neighbour',
    'Node',
    'NodeMetadata',
    'NodeGroupToRackController',
    'Notification',
    'OwnerData',
    'PackageRepository',
    'Partition',
    'PartitionTable',
    'PhysicalBlockDevice',
    'PhysicalInterface',
    'Pod',
    'PodHints',
    'PodStoragePool',
    'RackController',
    'RAID',
    "RBACLastSync",
    'RBACSync',
    'RDNS',
    'RegionController',
    'RegionControllerProcess',
    'RegionControllerProcessEndpoint',
    'RegionRackRPCConnection',
    'ResourcePool',
    'RootKey',
    'Service',
    'signals',
    'Space',
    'SSHKey',
    'SSLKey',
    'StaticIPAddress',
    'StaticRoute',
    'Subnet',
    'Switch',
    'Tag',
    'Template',
    'UnknownInterface',
    'UserProfile',
    'VersionedTextFile',
    'VirtualBlockDevice',
    'VLAN',
    'VLANInterface',
    'VolumeGroup',
    'Zone',
]

from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import (
    _user_has_perm,
    User,
    UserManager,
)
from django.core.exceptions import ViewDoesNotExist
from django.db.models.signals import post_save
from maasserver import logger
from maasserver.enum import NODE_TYPE
from maasserver.models.blockdevice import BlockDevice
from maasserver.models.bmc import (
    BMC,
    BMCRoutableRackControllerRelationship,
    Pod,
)
from maasserver.models.bootresource import BootResource
from maasserver.models.bootresourcefile import BootResourceFile
from maasserver.models.bootresourceset import BootResourceSet
from maasserver.models.bootsource import BootSource
from maasserver.models.bootsourcecache import BootSourceCache
from maasserver.models.bootsourceselection import BootSourceSelection
from maasserver.models.cacheset import CacheSet
from maasserver.models.config import Config
from maasserver.models.controllerinfo import ControllerInfo
from maasserver.models.dhcpsnippet import DHCPSnippet
from maasserver.models.discovery import Discovery
from maasserver.models.dnsdata import DNSData
from maasserver.models.dnspublication import DNSPublication
from maasserver.models.dnsresource import DNSResource
from maasserver.models.domain import Domain
from maasserver.models.event import Event
from maasserver.models.eventtype import EventType
from maasserver.models.fabric import Fabric
from maasserver.models.fannetwork import FanNetwork
from maasserver.models.filestorage import FileStorage
from maasserver.models.filesystem import Filesystem
from maasserver.models.filesystemgroup import (
    Bcache,
    FilesystemGroup,
    RAID,
    VolumeGroup,
)
from maasserver.models.globaldefault import GlobalDefault
from maasserver.models.interface import (
    BondInterface,
    BridgeInterface,
    Interface,
    PhysicalInterface,
    UnknownInterface,
    VLANInterface,
)
from maasserver.models.iprange import IPRange
from maasserver.models.iscsiblockdevice import ISCSIBlockDevice
from maasserver.models.keysource import KeySource
from maasserver.models.largefile import LargeFile
from maasserver.models.licensekey import LicenseKey
from maasserver.models.mdns import MDNS
from maasserver.models.neighbour import Neighbour
from maasserver.models.node import (
    Controller,
    Device,
    Machine,
    Node,
    NodeGroupToRackController,
    RackController,
    RegionController,
)
from maasserver.models.nodemetadata import NodeMetadata
from maasserver.models.notification import Notification
from maasserver.models.ownerdata import OwnerData
from maasserver.models.packagerepository import PackageRepository
from maasserver.models.partition import Partition
from maasserver.models.partitiontable import PartitionTable
from maasserver.models.physicalblockdevice import PhysicalBlockDevice
from maasserver.models.podhints import PodHints
from maasserver.models.podstoragepool import PodStoragePool
from maasserver.models.rbacsync import (
    RBACLastSync,
    RBACSync,
)
from maasserver.models.rdns import RDNS
from maasserver.models.regioncontrollerprocess import RegionControllerProcess
from maasserver.models.regioncontrollerprocessendpoint import (
    RegionControllerProcessEndpoint,
)
from maasserver.models.regionrackrpcconnection import RegionRackRPCConnection
from maasserver.models.resourcepool import ResourcePool
from maasserver.models.rootkey import RootKey
from maasserver.models.service import Service
from maasserver.models.space import Space
from maasserver.models.sshkey import SSHKey
from maasserver.models.sslkey import SSLKey
from maasserver.models.staticipaddress import StaticIPAddress
from maasserver.models.staticroute import StaticRoute
from maasserver.models.subnet import Subnet
from maasserver.models.switch import Switch
from maasserver.models.tag import Tag
from maasserver.models.template import Template
from maasserver.models.user import create_user
from maasserver.models.userprofile import UserProfile
from maasserver.models.versionedtextfile import VersionedTextFile
from maasserver.models.virtualblockdevice import VirtualBlockDevice
from maasserver.models.vlan import VLAN
from maasserver.models.zone import Zone
from maasserver.permissions import NodePermission
from maasserver.utils.django_urls import (
    get_callable,
    get_resolver,
    get_script_prefix,
)
from piston3.doc import HandlerDocumentation
from provisioningserver.utils import is_instance_or_subclass

# Connect post-creation methods for models.
post_save.connect(create_user, sender=User)


# Monkey patch django.contrib.auth.models.User to force email to be unique and
# allow null.
User._meta.get_field('email')._unique = True
User._meta.get_field('email').blank = False
User._meta.get_field('email').null = True

_normalize_email = UserManager.normalize_email


def normalize_email(cls, email):
    if not email:
        return None
    return _normalize_email(email)

UserManager.normalize_email = classmethod(normalize_email)


# Monkey patch django.contrib.auth.models.User to skip the `is_superuser`
# bypass. We want the `MAASAuthorizationBackend` to always be called.
def has_perm(self, perm, obj=None):
    return _user_has_perm(self, perm, obj)

User.has_perm = has_perm


# Monkey patch piston's usage of Django's get_resolver to be compatible
# with Django 1.4.
# XXX: rvb 2012-09-21 bug=1054040
# See https://bitbucket.org/jespern/django-piston/issue/218 for details.
def get_resource_uri_template(self):
    """
    URI template processor.
    See http://bitworking.org/projects/URI-Templates/
    """
    def _convert(template, params=[]):
        """URI template converter"""
        paths = template % dict([p, "{%s}" % p] for p in params)
        return '%s%s' % (get_script_prefix(), paths)
    try:
        resource_uri = self.handler.resource_uri()
        components = [None, [], {}]

        for i, value in enumerate(resource_uri):
            components[i] = value
        lookup_view, args, kwargs = components
        try:
            lookup_view = get_callable(lookup_view)
        except (ImportError, ViewDoesNotExist):
            # Emulate can_fail=True from earlier django versions.
            pass

        possibilities = get_resolver(None).reverse_dict.getlist(lookup_view)
        # The monkey patch is right here: we need to cope with 'possibilities'
        # being a list of tuples with 2 or 3 elements.
        for possibility_data in possibilities:
            possibility = possibility_data[0]
            for result, params in possibility:
                if args:
                    if len(args) != len(params):
                        continue
                    return _convert(result, params)
                else:
                    if set(kwargs.keys()) != set(params):
                        continue
                    return _convert(result, params)
    except:
        return None

HandlerDocumentation.get_resource_uri_template = get_resource_uri_template

# Monkey patch the property resource_uri_template: it hold a reference to
# get_resource_uri_template.
HandlerDocumentation.resource_uri_template = (
    property(get_resource_uri_template))

# Some actions are applied to model object types global to MAAS; not
# necessarily a particular object. The following objects cannot be created or
# changed by non-administrative users, but superusers can always create, read
# write, or delete them.
UNRESTRICTED_READ_MODELS = (
    DNSData,
    DNSResource,
    Domain,
    Fabric,
    FanNetwork,
    ResourcePool,
    Space,
    Subnet,
    StaticRoute,
    VLAN
)

# The following model objects are restricted from non-administrative users.
# They cannot be seen (or created, or modified, or deleted) by "normal" users.
ADMIN_RESTRICTED_MODELS = (
    Discovery,
)

# ADMIN_PERMISSIONS applies to the model objects in ADMIN_RESTRICTED_MODELS.
# These model objects are restricted to administrators only; permission checks
# will return True for administrators given any of the following permissions:
ADMIN_PERMISSIONS = (
    NodePermission.view,
    NodePermission.edit,
    NodePermission.admin,
)


class MAASAuthorizationBackend(ModelBackend):

    supports_object_permissions = True

    def authenticate(self, request, username=None, password=None, **kwargs):
        external_auth_info = getattr(request, 'external_auth_info', None)
        # use getattr so that tests that don't include the middleware don't
        # explode
        if external_auth_info:
            # Don't allow username/password logins with external authentication
            return
        authenticated = super().authenticate(
            request, username=username, password=password, **kwargs)
        if authenticated:
            user = User.objects.get(username=username)
            if not user.userprofile.is_local:
                return
        return authenticated

    def has_perm(self, user, perm, obj=None):
        if not user.is_active:
            # Deactivated users, and in particular the node-init user,
            # are prohibited from accessing maasserver services.
            return False

        from maasserver.rbac import rbac
        rbac_enabled = rbac.is_enabled()
        visible_pools, admin_pools = [], []
        if rbac_enabled:
            visible_pools = rbac.get_resource_pools(
                user.username, 'view').values_list(
                    'id', flat=True)
            admin_pools = rbac.get_resource_pools(
                user.username, 'admin-machines').values_list(
                    'id', flat=True)

        if isinstance(obj, (Node, BlockDevice, FilesystemGroup)):
            if isinstance(obj, BlockDevice):
                obj = obj.node
            elif isinstance(obj, FilesystemGroup):
                obj = obj.get_node()
            if perm == NodePermission.view:
                return self._can_view(
                    rbac_enabled, user, obj, visible_pools, admin_pools)
            elif perm == NodePermission.edit:
                can_edit = self._can_edit(
                    rbac_enabled, user, obj, visible_pools, admin_pools)
                return not obj.locked and can_edit
            elif perm == NodePermission.lock:
                # only machines can be locked
                can_edit = self._can_edit(
                    rbac_enabled, user, obj, visible_pools, admin_pools)
                return obj.pool_id is not None and can_edit
            elif perm == NodePermission.admin:
                return self._can_admin(
                    rbac_enabled, user, obj, admin_pools)
            else:
                raise NotImplementedError(
                    'Invalid permission check (invalid permission name: %s).' %
                    perm)
        elif isinstance(obj, Interface):
            node = obj.get_node()
            if node is None:
                # Doesn't matter the permission level if the interface doesn't
                # have a node, the user must be a global admin.
                return user.is_superuser
            if perm == NodePermission.view:
                return self._can_view(
                    rbac_enabled, user, node, visible_pools, admin_pools)
            elif perm == NodePermission.edit:
                # Machine interface can only be modified by an administrator
                # of the machine. Even the owner of the machine cannot modify
                # the interfaces on that machine, unless they have
                # administrator rights.
                if node.node_type == NODE_TYPE.MACHINE:
                    return self._can_admin(
                        rbac_enabled, user, node, admin_pools)
                # Other node types must be editable by the user.
                return self._can_edit(
                    rbac_enabled, user, node, visible_pools, admin_pools)
            elif perm == NodePermission.admin:
                # Admin permission is solely granted to superusers.
                return self._can_admin(
                    rbac_enabled, user, node, admin_pools)
            else:
                raise NotImplementedError(
                    'Invalid permission check (invalid permission name: %s).' %
                    perm)
        elif is_instance_or_subclass(obj, UNRESTRICTED_READ_MODELS):
            # This model is classified under 'unrestricted read' for any
            # logged-in user; so everyone can view, but only an admin can
            # do anything else.
            if perm == NodePermission.view:
                return True
            elif perm in ADMIN_PERMISSIONS:
                # Admin permission is solely granted to superusers.
                return user.is_superuser
            else:
                raise NotImplementedError(
                    'Invalid permission check (invalid permission name: %s).' %
                    perm)
        elif is_instance_or_subclass(obj, ADMIN_RESTRICTED_MODELS):
            # Only administrators are allowed to read/write these objects.
            if perm in ADMIN_PERMISSIONS:
                return user.is_superuser
            else:
                raise NotImplementedError(
                    'Invalid permission check (invalid permission name: %s).' %
                    perm)
        else:
            raise NotImplementedError(
                'Invalid permission check (invalid object type).')

    def _can_view(
            self, rbac_enabled, user, machine, visible_pools, admin_pools):
        if machine.pool_id is None:
            # Only machines are filtered for view access.
            return True
        if rbac_enabled:
            # Machine not owned by the user must be in the admin_pools for
            # the user to be able to view the machine.
            if machine.owner_id is not None and machine.owner_id != user.id:
                return machine.pool_id in admin_pools
            # Machine is not owned or owned by the user so must be in either
            # pool for the user to view it.
            return (
                machine.pool_id in visible_pools or
                machine.pool_id in admin_pools)
        return (
            machine.owner_id is None or
            machine.owner_id == user.id or
            user.is_superuser)

    def _can_edit(
            self, rbac_enabled, user, machine, visible_pools, admin_pools):
        is_owner = machine.owner_id == user.id
        if rbac_enabled:
            can_view = self._can_view(
                rbac_enabled, user, machine, visible_pools, admin_pools)
            can_admin = self._can_admin(
                rbac_enabled, user, machine, admin_pools)
            return (is_owner and can_view) or can_admin
        return is_owner or user.is_superuser

    def _can_admin(self, rbac_enabled, user, machine, admin_pools):
        if machine.pool_id is None:
            # Not a machine to be admin on this must have global admin.
            return user.is_superuser
        if rbac_enabled:
            return machine.pool_id in admin_pools
        return user.is_superuser


# Ensure that all signals modules are loaded.
from maasserver.models import signals
