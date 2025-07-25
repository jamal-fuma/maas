# Copyright 2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import asyncio
import os

from simplestreams.mirrors import UrlMirrorReader
from simplestreams.util import path_from_mirror_url
import structlog

from maascommon.utils.fs import tempdir
from maasservicelayer.builders.bootsources import BootSourceBuilder
from maasservicelayer.context import Context
from maasservicelayer.db.filters import QuerySpec
from maasservicelayer.db.repositories.bootsourcecache import (
    BootSourceCacheClauseFactory,
)
from maasservicelayer.db.repositories.bootsources import BootSourcesRepository
from maasservicelayer.db.repositories.bootsourceselections import (
    BootSourceSelectionClauseFactory,
)
from maasservicelayer.models.bootsources import BootSource
from maasservicelayer.services.base import BaseService
from maasservicelayer.services.bootsourcecache import BootSourceCacheService
from maasservicelayer.services.bootsourceselections import (
    BootSourceSelectionsService,
)
from maasservicelayer.services.configurations import ConfigurationsService
from maasservicelayer.utils.images.boot_image_mapping import BootImageMapping
from maasservicelayer.utils.images.helpers import get_signing_policy
from maasservicelayer.utils.images.keyrings import (
    calculate_keyring_name,
    write_keyring,
)
from maasservicelayer.utils.images.repo_dumper import RepoDumper

logger = structlog.getLogger()


class BootSourcesService(
    BaseService[BootSource, BootSourcesRepository, BootSourceBuilder]
):
    def __init__(
        self,
        context: Context,
        repository: BootSourcesRepository,
        boot_source_cache_service: BootSourceCacheService,
        boot_source_selections_service: BootSourceSelectionsService,
        configuration_service: ConfigurationsService,
    ) -> None:
        super().__init__(context, repository)
        self.boot_source_cache_service = boot_source_cache_service
        self.boot_source_selections_service = boot_source_selections_service
        self.configuration_service = configuration_service

    async def post_delete_hook(self, resource: BootSource) -> None:
        # cascade delete
        await self.boot_source_cache_service.delete_many(
            query=QuerySpec(
                where=BootSourceCacheClauseFactory.with_boot_source_id(
                    resource.id
                )
            )
        )
        await self.boot_source_selections_service.delete_many(
            query=QuerySpec(
                where=BootSourceSelectionClauseFactory.with_boot_source_id(
                    resource.id
                )
            )
        )

    async def fetch(
        self,
        source_url: str,
        keyring_path: str | None = None,
        keyring_data: bytes | None = None,
        validate_products: bool = True,
    ) -> BootImageMapping:
        """Download image metadata from upstream Simplestreams repo.

        :param source_url: The path to a Simplestreams repo.
        :param keyring_path: Optional filepath to the keyring for verifying the repo's signatures.
        :param keyring_data: Optional keyring data for verifying the repo's signatures.
        :param validate_products: Whether to validate products in the boot
            sources.
        :return: A `BootImageMapping` describing available boot resources.
        """
        user_agent = await self.configuration_service.get_maas_user_agent()
        return await asyncio.to_thread(
            self._fetch,
            source_url,
            user_agent,
            keyring_path,
            keyring_data,
            validate_products,
        )

    def _fetch(
        self,
        source_url: str,
        user_agent: str,
        keyring_path: str | None = None,
        keyring_data: bytes | None = None,
        validate_products: bool = True,
    ) -> BootImageMapping:
        logger.info(f"Downloading image descriptions from '{source_url}'.")
        mirror, rpath = path_from_mirror_url(source_url, None)

        # The simplestreams library uses an optional path to the keyring file,
        # but we want to allow the user to provide a keyring file path _or_ the
        # (base64-encoded) keyring data directly.
        if keyring_data:
            # Write `keyring_data` to a temporary file and use that as `keyring_path`.
            with tempdir("keyrings") as keyrings_dir:
                keyring_path = os.path.join(
                    keyrings_dir, calculate_keyring_name(source_url)
                )
                write_keyring(keyring_path, keyring_data)

                # The rest of the logic needs to exist in the same `tempdir` context manager so that the keyring files
                # are still present when trying to obtain the image descriptions.
                return self._sync_and_populate_boot_mapping(
                    mirror, rpath, user_agent, keyring_path, validate_products
                )
        else:
            return self._sync_and_populate_boot_mapping(
                mirror,
                rpath,
                user_agent,
                keyring_path,  # pyright: ignore[reportArgumentType]
                validate_products,
            )

    def _sync_and_populate_boot_mapping(
        self,
        mirror: str,
        rpath: str,
        user_agent: str,
        keyring_path: str,
        validate_products: bool = True,
    ) -> BootImageMapping:
        policy = get_signing_policy(rpath, keyring_path)

        try:
            reader = UrlMirrorReader(
                mirror, policy=policy, user_agent=user_agent
            )
        except TypeError:
            # UrlMirrorReader doesn't support the user_agent argument.
            # simplestream >=bzr429 is required for this feature.
            reader = UrlMirrorReader(mirror, policy=policy)

        boot_images_dict = BootImageMapping()
        dumper = RepoDumper(
            boot_images_dict, validate_products=validate_products
        )
        dumper.sync(reader, rpath)
        return boot_images_dict
