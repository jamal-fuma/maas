# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""
MAAS Site Manager Connector workflows
"""

import asyncio
import dataclasses
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

from aiohttp import ClientSession, ClientTimeout
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.sql.functions import count
from sqlalchemy.sql.operators import eq
from temporalio import activity, workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ApplicationError
from temporalio.workflow import ParentClosePolicy
import yaml

from maasapiserver.common.db import Database
from maasapiserver.common.db.tables import NodeTable
from maasserver.enum import NODE_STATUS, NODE_TYPE
from maastemporalworker.workflow.activity import ActivityBase

HEARTBEAT_TIMEOUT = timedelta(seconds=10)
MSM_TIMEOUT = timedelta(minutes=15)
MSM_POLL_INTERVAL = timedelta(minutes=1)
MSM_SECRET = "msm-connector"


@dataclasses.dataclass
class MSMEnrolParam:
    site_name: str
    site_url: str
    url: str
    jwt: str
    cluster_uuid: str
    metainfo: str | None = None


@dataclasses.dataclass
class MSMConnectorParam:
    url: str
    jwt: str


@dataclasses.dataclass
class MachineStatsByStatus:
    """Machine counts by status."""

    allocated: int = 0
    deployed: int = 0
    ready: int = 0
    error: int = 0
    other: int = 0


@dataclasses.dataclass
class MSMHeartbeatParam:
    sm_url: str
    jwt: str
    site_name: str
    site_url: str
    status: MachineStatsByStatus | None = None


class MSMConnectorActivity(ActivityBase):
    def __init__(
        self, db: Database, connection: AsyncConnection | None = None
    ):
        super().__init__(db, connection)
        self._session = self._create_session()

    def _create_session(self) -> ClientSession:
        timeout = ClientTimeout(total=60 * 60, sock_read=120)
        return ClientSession(trust_env=True, timeout=timeout)

    @activity.defn(name="msm-send-enrol")
    async def send_enrol(
        self, input: MSMEnrolParam
    ) -> tuple[bool, dict[str, Any] | None]:
        """Send enrolment request.

        Args:
            input (MSMEnrolParam): Enrolment parameters

        Returns:
            bool: whether the request was successful
        """
        activity.logger.debug(f"attempting to enrol to {input.url}")
        headers = {
            "Authorization": f"bearer {input.jwt}",
        }
        data = {
            "name": input.site_name,
            "url": input.site_url,
            "cluster_uuid": input.cluster_uuid,
            **(yaml.safe_load(input.metainfo) if input.metainfo else {}),
        }

        async with self._session.post(
            input.url, json=data, headers=headers
        ) as response:
            match response.status:
                case 404:
                    activity.logger.error("Enrolment URL not found, aborting")
                    return (
                        False,
                        {
                            "status": response.status,
                            "reason": response.reason,
                        },
                    )
                case 202:
                    return (True, None)
                case _:
                    raise ApplicationError(
                        f"got unexpected return code: HTTP {response.status}"
                    )

    @activity.defn(name="msm-check-enrol")
    async def check_enrol(self, input: MSMEnrolParam) -> str | None:
        """Check the enrolment status.

        Args:
            input (MSMEnrolParam): Enrolment parameters

        Returns:
            str: a new JWT if the enrolment was completed
        """
        headers = {
            "Authorization": f"bearer {input.jwt}",
        }
        async with self._session.get(input.url, headers=headers) as response:
            match response.status:
                case 204:
                    raise ApplicationError("waiting for MSM enrolment")
                case 200:
                    data = await response.json()
                    return data["access_token"]
                case 404:
                    activity.logger.error(
                        "Enrolment cancelled by MSM, aborting"
                    )
                    return None
                case _:
                    raise ApplicationError(
                        f"got unexpected return code: HTTP {response.status}"
                    )

    @activity.defn(name="msm-set-enrol")
    async def set_enrol(self, input: MSMConnectorParam) -> None:
        """Set enrolment data in the DB.

        Args:
            input (MSMConnectorParam): MSM connection data
        """
        from maasapiserver.v3.db.secrets import SecretsRepository

        async with self.start_transaction() as tx:
            # TODO add Vault support
            repo = SecretsRepository(tx)
            await repo.create_or_update(
                f"global/{MSM_SECRET}",
                {
                    "url": input.url,
                    "jwt": input.jwt,
                },
            )

    @activity.defn(name="msm-get-heartbeat-data")
    async def get_heartbeat_data(self) -> MachineStatsByStatus:
        """Get heartbeat data from MAAS DB

        Returns:
            MachineStatsByStatus: machine counters
        """
        ret = MachineStatsByStatus()
        stmt = (
            select(NodeTable.c.status, count(NodeTable.c.id).label("total"))
            .select_from(NodeTable)
            .where(eq(NodeTable.c.node_type, NODE_TYPE.MACHINE))
            .group_by(NodeTable.c.status)
        )
        async with self.start_transaction() as tx:
            result = await tx.execute(stmt)
            for row in result.all():
                match row.status:
                    case NODE_STATUS.ALLOCATED:
                        ret.allocated += row.total
                    case NODE_STATUS.DEPLOYED:
                        ret.deployed += row.total
                    case NODE_STATUS.READY:
                        ret.ready += row.total
                    case (
                        NODE_STATUS.FAILED_COMMISSIONING
                        | NODE_STATUS.FAILED_DEPLOYMENT
                        | NODE_STATUS.FAILED_DISK_ERASING
                        | NODE_STATUS.FAILED_ENTERING_RESCUE_MODE
                        | NODE_STATUS.FAILED_EXITING_RESCUE_MODE
                        | NODE_STATUS.FAILED_RELEASING
                        | NODE_STATUS.FAILED_TESTING
                    ):
                        ret.error += row.total
                    case _:
                        ret.other += row.total

        return ret

    @activity.defn(name="msm-send-heartbeat")
    async def send_heartbeat(self, input: MSMHeartbeatParam) -> int:
        """Send heartbeat data to MSM.

        Args:
            input (MSMHeartbeatParam): MSM heartbeat data

        Returns:
            int: interval for the next update
        """
        headers = {
            "Authorization": f"bearer {input.jwt}",
        }
        data = {
            "name": input.site_name,
            "url": input.site_url,
            "machines_by_status": dataclasses.asdict(input.status),
        }

        async with self._session.post(
            input.sm_url, json=data, headers=headers
        ) as response:
            match response.status:
                case 200:
                    return int(
                        response.headers["MSM-Heartbeat-Interval-Seconds"]
                    )
                case 401 | 404:
                    activity.logger.error(
                        "Enrolment cancelled by MSM, aborting"
                    )
                    return -1
                case _:
                    raise ApplicationError(
                        f"got unexpected return code: HTTP {response.status}"
                    )


@workflow.defn(name="msm-enrol-site", sandboxed=False)
class MSMEnrolSiteWorkflow:
    """Enrol this site to MSM."""

    def __init__(self) -> None:
        self._pending = False
        self._enrolment_error = None

    @workflow.run
    async def run(self, input: MSMEnrolParam) -> None:
        """Run workflow.

        Args:
            input (MSMEnrolParam): Enrolment data
        """
        workflow.logger.info(f"enrolling to {input.url}")
        self._pending = True
        (sent, error) = await workflow.execute_activity(
            "msm-send-enrol",
            input,
            start_to_close_timeout=MSM_TIMEOUT,
        )
        if not sent:
            self._pending = False
            self._enrolment_error = error
            workflow.logger.error(f"failed to enrol to {input.url}, aborting")
            return
        else:
            # important we set this to {} instead of None so
            # the CLI command knows when the request was sent
            # without error
            self._enrolment_error = {}

        param = MSMConnectorParam(
            url=input.url,
            jwt=input.jwt,
        )
        await workflow.execute_activity(
            "msm-set-enrol",
            param,
            start_to_close_timeout=MSM_TIMEOUT,
        )

        new_jwt = await workflow.execute_activity(
            "msm-check-enrol",
            input,
            start_to_close_timeout=MSM_TIMEOUT,
            retry_policy=RetryPolicy(
                backoff_coefficient=1.0,
                initial_interval=MSM_POLL_INTERVAL,
            ),
        )
        if new_jwt is None:
            self._pending = False
            workflow.logger.error("enrolment cancelled by MSM")
            return

        new_url = (
            urlparse(input.url)._replace(path="/site/v1/details").geturl()
        )
        param.url = new_url
        param.jwt = new_jwt
        await workflow.execute_activity(
            "msm-set-enrol",
            param,
            start_to_close_timeout=MSM_TIMEOUT,
        )

        await workflow.start_child_workflow(
            "msm-heartbeat",
            MSMHeartbeatParam(
                sm_url=new_url,
                jwt=new_jwt,
                site_name=input.site_name,
                site_url=input.site_url,
            ),
            id="msm-heartbeat:region",
            id_reuse_policy=WorkflowIDReusePolicy.TERMINATE_IF_RUNNING,
            parent_close_policy=ParentClosePolicy.ABANDON,
        )

        self._pending = False

    @workflow.query(name="is-pending")
    def is_pending(self) -> bool:
        return self._pending

    @workflow.query(name="enrolment-error")
    def enrolment_error(self) -> dict[str, Any] | None:
        return self._enrolment_error


@workflow.defn(name="msm-withdraw", sandboxed=False)
class MSMWithdrawWorkflow:
    """Withdraw this site from MSM."""

    @workflow.run
    async def run(self, input: MSMConnectorParam) -> None:
        """Run workflow.

        Args:
            input (MSMConnectorParam): Withdraw data
        """


@workflow.defn(name="msm-heartbeat", sandboxed=False)
class MSMHeartbeatWorkflow:
    """Send periodic heartbeats to MSM."""

    def __init__(self) -> None:
        self._running = False

    @workflow.run
    async def run(self, input: MSMHeartbeatParam) -> None:
        """Run workflow.

        Args:
            input (MSMHeartbeatParam): Heartbeat data
        """
        self._running = True
        next_update = 0
        while next_update >= 0:
            data = await workflow.execute_activity(
                "msm-get-heartbeat-data",
                start_to_close_timeout=MSM_TIMEOUT,
            )
            next_update = await workflow.execute_activity(
                "msm-send-heartbeat",
                dataclasses.replace(input, status=data),
                start_to_close_timeout=MSM_TIMEOUT,
                retry_policy=RetryPolicy(
                    backoff_coefficient=1.0,
                    initial_interval=timedelta(seconds=next_update),
                ),
            )
            workflow.logger.debug(f"next refresh in {next_update} seconds")
            if next_update > 0:
                await asyncio.sleep(next_update)
        self._running = False

    @workflow.query(name="is-running")
    def is_running(self) -> bool:
        return self._running
