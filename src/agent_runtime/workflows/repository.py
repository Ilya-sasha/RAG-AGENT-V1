from __future__ import annotations

import base64
import binascii
import json
from datetime import UTC, datetime

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_runtime.domain.enums import RunStatus
from agent_runtime.domain.models import (
    WorkflowRunLinkRecord,
    WorkflowTemplateRecord,
    WorkflowTemplateVersionRecord,
)
from agent_runtime.state.tables import (
    RunTable,
    WorkflowRunLinkTable,
    WorkflowTemplateTable,
    WorkflowTemplateVersionTable,
)

WORKFLOW_LIST_CURSOR_ERROR_MESSAGE = "invalid workflow list cursor"
WORKFLOW_LIST_CURSOR_VERSION = 1
WORKFLOW_LIST_CURSOR_CREATED_AT_KEY = "created_at"
WORKFLOW_LIST_CURSOR_WORKFLOW_ID_KEY = "workflow_id"
WORKFLOW_RUN_LIST_CURSOR_ERROR_MESSAGE = "invalid workflow run list cursor"
WORKFLOW_RUN_LIST_CURSOR_VERSION = 1
WORKFLOW_RUN_LIST_CURSOR_CREATED_AT_KEY = "created_at"
WORKFLOW_RUN_LIST_CURSOR_RUN_ID_KEY = "run_id"


def utc_now() -> datetime:
    return datetime.now(UTC)


def _format_cursor_datetime(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def encode_workflow_list_cursor(*, created_at: datetime, workflow_id: str) -> str:
    payload = {
        "v": WORKFLOW_LIST_CURSOR_VERSION,
        WORKFLOW_LIST_CURSOR_CREATED_AT_KEY: _format_cursor_datetime(created_at),
        WORKFLOW_LIST_CURSOR_WORKFLOW_ID_KEY: workflow_id,
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return encoded.decode("ascii")


def decode_workflow_list_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
    except (UnicodeEncodeError, binascii.Error, json.JSONDecodeError, ValueError, TypeError) as exc:
        raise ValueError(WORKFLOW_LIST_CURSOR_ERROR_MESSAGE) from exc

    if (
        not isinstance(payload, dict)
        or payload.get("v") != WORKFLOW_LIST_CURSOR_VERSION
        or not isinstance(payload.get(WORKFLOW_LIST_CURSOR_CREATED_AT_KEY), str)
        or not isinstance(payload.get(WORKFLOW_LIST_CURSOR_WORKFLOW_ID_KEY), str)
        or not payload[WORKFLOW_LIST_CURSOR_WORKFLOW_ID_KEY]
    ):
        raise ValueError(WORKFLOW_LIST_CURSOR_ERROR_MESSAGE)

    try:
        created_at = datetime.fromisoformat(
            payload[WORKFLOW_LIST_CURSOR_CREATED_AT_KEY].replace("Z", "+00:00")
        ).astimezone(UTC)
    except ValueError as exc:
        raise ValueError(WORKFLOW_LIST_CURSOR_ERROR_MESSAGE) from exc

    return created_at, payload[WORKFLOW_LIST_CURSOR_WORKFLOW_ID_KEY]


def encode_workflow_run_list_cursor(*, created_at: datetime, run_id: str) -> str:
    payload = {
        "v": WORKFLOW_RUN_LIST_CURSOR_VERSION,
        WORKFLOW_RUN_LIST_CURSOR_CREATED_AT_KEY: _format_cursor_datetime(created_at),
        WORKFLOW_RUN_LIST_CURSOR_RUN_ID_KEY: run_id,
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return encoded.decode("ascii")


def decode_workflow_run_list_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
    except (UnicodeEncodeError, binascii.Error, json.JSONDecodeError, ValueError, TypeError) as exc:
        raise ValueError(WORKFLOW_RUN_LIST_CURSOR_ERROR_MESSAGE) from exc

    if (
        not isinstance(payload, dict)
        or payload.get("v") != WORKFLOW_RUN_LIST_CURSOR_VERSION
        or not isinstance(payload.get(WORKFLOW_RUN_LIST_CURSOR_CREATED_AT_KEY), str)
        or not isinstance(payload.get(WORKFLOW_RUN_LIST_CURSOR_RUN_ID_KEY), str)
        or not payload[WORKFLOW_RUN_LIST_CURSOR_RUN_ID_KEY]
    ):
        raise ValueError(WORKFLOW_RUN_LIST_CURSOR_ERROR_MESSAGE)

    try:
        created_at = datetime.fromisoformat(
            payload[WORKFLOW_RUN_LIST_CURSOR_CREATED_AT_KEY].replace("Z", "+00:00")
        ).astimezone(UTC)
    except ValueError as exc:
        raise ValueError(WORKFLOW_RUN_LIST_CURSOR_ERROR_MESSAGE) from exc

    return created_at, payload[WORKFLOW_RUN_LIST_CURSOR_RUN_ID_KEY]


class WorkflowRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_template(
        self,
        template: WorkflowTemplateRecord,
        version: WorkflowTemplateVersionRecord,
    ) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                session.add(
                    WorkflowTemplateTable(
                        template_id=template.template_id,
                        tenant_id=template.tenant_id,
                        name=template.name,
                        description=template.description,
                        status=template.status,
                        latest_version=template.latest_version,
                        latest_published_version=template.latest_published_version,
                        archived_at=template.archived_at,
                        created_at=template.created_at,
                        updated_at=template.updated_at,
                    )
                )
                session.add(
                    WorkflowTemplateVersionTable(
                        tenant_id=template.tenant_id,
                        template_id=version.template_id,
                        version=version.version,
                        definition=version.definition,
                        input_schema=version.input_schema,
                        source_version=version.source_version,
                        is_published=version.is_published,
                        published_at=version.published_at,
                        created_at=version.created_at,
                        created_by=version.created_by,
                    )
                )

    async def create_template_version(
        self,
        tenant_id: str,
        template_id: str,
        version: WorkflowTemplateVersionRecord,
    ) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                template_row = (
                    await session.execute(
                        select(WorkflowTemplateTable).where(
                            WorkflowTemplateTable.tenant_id == tenant_id,
                            WorkflowTemplateTable.template_id == template_id,
                        )
                    )
                ).scalar_one()
                template_row.latest_version = version.version
                template_row.status = "draft"
                template_row.archived_at = None
                template_row.updated_at = utc_now()
                session.add(
                    WorkflowTemplateVersionTable(
                        tenant_id=tenant_id,
                        template_id=template_id,
                        version=version.version,
                        definition=version.definition,
                        input_schema=version.input_schema,
                        source_version=version.source_version,
                        is_published=version.is_published,
                        published_at=version.published_at,
                        created_at=version.created_at,
                        created_by=version.created_by,
                    )
                )

    async def publish_version(self, tenant_id: str, template_id: str, version: int) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                version_row = (
                    await session.execute(
                        select(WorkflowTemplateVersionTable).where(
                            WorkflowTemplateVersionTable.tenant_id == tenant_id,
                            WorkflowTemplateVersionTable.template_id == template_id,
                            WorkflowTemplateVersionTable.version == version,
                        )
                    )
                ).scalar_one()
                version_row.is_published = True
                version_row.published_at = utc_now()

                template_row = (
                    await session.execute(
                        select(WorkflowTemplateTable).where(
                            WorkflowTemplateTable.tenant_id == tenant_id,
                            WorkflowTemplateTable.template_id == template_id,
                        )
                    )
                ).scalar_one()
                published_max_version = (
                    await session.execute(
                        select(WorkflowTemplateVersionTable.version)
                        .where(
                            WorkflowTemplateVersionTable.tenant_id == tenant_id,
                            WorkflowTemplateVersionTable.template_id == template_id,
                            WorkflowTemplateVersionTable.is_published.is_(True),
                        )
                        .order_by(WorkflowTemplateVersionTable.version.desc())
                        .limit(1)
                    )
                ).scalar_one()
                has_newer_unpublished = (
                    await session.execute(
                        select(WorkflowTemplateVersionTable.version)
                        .where(
                            WorkflowTemplateVersionTable.tenant_id == tenant_id,
                            WorkflowTemplateVersionTable.template_id == template_id,
                            WorkflowTemplateVersionTable.is_published.is_(False),
                            WorkflowTemplateVersionTable.version > published_max_version,
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none() is not None
                template_row.latest_published_version = published_max_version
                template_row.status = "draft" if has_newer_unpublished else "published"
                template_row.updated_at = utc_now()

    async def get_template(self, tenant_id: str, template_id: str) -> WorkflowTemplateRecord | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(WorkflowTemplateTable).where(
                        WorkflowTemplateTable.tenant_id == tenant_id,
                        WorkflowTemplateTable.template_id == template_id,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return self._to_template_record(row)

    async def get_template_version(
        self,
        tenant_id: str,
        template_id: str,
        version: int,
    ) -> WorkflowTemplateVersionRecord | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(WorkflowTemplateVersionTable).where(
                        WorkflowTemplateVersionTable.tenant_id == tenant_id,
                        WorkflowTemplateVersionTable.template_id == template_id,
                        WorkflowTemplateVersionTable.version == version,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return self._to_template_version_record(row)

    async def get_latest_published_version(
        self,
        tenant_id: str,
        template_id: str,
    ) -> WorkflowTemplateVersionRecord | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(WorkflowTemplateVersionTable)
                    .where(
                        WorkflowTemplateVersionTable.tenant_id == tenant_id,
                        WorkflowTemplateVersionTable.template_id == template_id,
                        WorkflowTemplateVersionTable.is_published.is_(True),
                    )
                    .order_by(WorkflowTemplateVersionTable.version.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return self._to_template_version_record(row)

    async def get_draft_version(
        self,
        tenant_id: str,
        template_id: str,
    ) -> WorkflowTemplateVersionRecord | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(WorkflowTemplateVersionTable)
                    .where(
                        WorkflowTemplateVersionTable.tenant_id == tenant_id,
                        WorkflowTemplateVersionTable.template_id == template_id,
                        WorkflowTemplateVersionTable.is_published.is_(False),
                    )
                    .order_by(WorkflowTemplateVersionTable.version.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return self._to_template_version_record(row)

    async def create_copied_draft_version(
        self,
        tenant_id: str,
        template_id: str,
        *,
        created_by: str | None = None,
    ) -> WorkflowTemplateVersionRecord:
        async with self._session_factory() as session:
            async with session.begin():
                template_row = await self._get_template_row(session, tenant_id, template_id)
                existing_draft_row = await self._get_latest_draft_row(session, tenant_id, template_id)
                if (
                    existing_draft_row is not None
                    and not (
                        existing_draft_row.version == 1
                        and template_row.latest_version == 1
                        and template_row.latest_published_version is None
                    )
                ):
                    raise ValueError("draft already exists")
                source_row = await self._get_version_row(session, tenant_id, template_id, template_row.latest_version)
                draft_version = template_row.latest_version + 1
                draft_row = WorkflowTemplateVersionTable(
                    tenant_id=tenant_id,
                    template_id=template_id,
                    version=draft_version,
                    definition=source_row.definition,
                    input_schema=source_row.input_schema,
                    source_version=source_row.version,
                    is_published=False,
                    published_at=None,
                    created_at=utc_now(),
                    created_by=created_by,
                )
                session.add(draft_row)
                template_row.latest_version = draft_version
                template_row.status = "draft"
                template_row.archived_at = None
                template_row.updated_at = utc_now()
                await session.flush()
                return self._to_template_version_record(draft_row)

    async def replace_draft_version(
        self,
        tenant_id: str,
        template_id: str,
        version: int,
        *,
        definition: dict,
        input_schema: dict,
    ) -> WorkflowTemplateVersionRecord:
        async with self._session_factory() as session:
            async with session.begin():
                version_row = await self._get_version_row(session, tenant_id, template_id, version)
                if version_row.is_published:
                    raise ValueError("cannot replace published workflow template version")
                version_row.definition = definition
                version_row.input_schema = input_schema
                await session.flush()
                return self._to_template_version_record(version_row)

    async def delete_draft_version(self, tenant_id: str, template_id: str, version: int) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                template_row = await self._get_template_row(session, tenant_id, template_id)
                version_row = await self._get_version_row(session, tenant_id, template_id, version)
                if version_row.is_published:
                    raise ValueError("cannot delete published workflow template version")

                if template_row.latest_version == version and template_row.latest_published_version is None:
                    raise ValueError("cannot delete last remaining draft version")

                await session.execute(
                    delete(WorkflowTemplateVersionTable).where(
                        WorkflowTemplateVersionTable.tenant_id == tenant_id,
                        WorkflowTemplateVersionTable.template_id == template_id,
                        WorkflowTemplateVersionTable.version == version,
                    )
                )

                remaining_versions = (
                    await session.execute(
                        select(WorkflowTemplateVersionTable)
                        .where(
                            WorkflowTemplateVersionTable.tenant_id == tenant_id,
                            WorkflowTemplateVersionTable.template_id == template_id,
                        )
                        .order_by(WorkflowTemplateVersionTable.version.desc())
                    )
                ).scalars().all()
                latest_row = remaining_versions[0]
                latest_published_row = next(
                    (row for row in remaining_versions if row.is_published),
                    None,
                )
                template_row.latest_version = latest_row.version
                template_row.latest_published_version = (
                    latest_published_row.version if latest_published_row is not None else None
                )
                template_row.status = "published" if latest_published_row is not None else "draft"
                template_row.updated_at = utc_now()

    async def list_template_versions(self, tenant_id: str, template_id: str) -> list[dict[str, object]]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(WorkflowTemplateVersionTable)
                    .where(
                        WorkflowTemplateVersionTable.tenant_id == tenant_id,
                        WorkflowTemplateVersionTable.template_id == template_id,
                    )
                    .order_by(WorkflowTemplateVersionTable.version.desc())
                )
            ).scalars()
            return [
                {
                    "version": row.version,
                    "status": "published" if row.is_published else "draft",
                    "is_published": row.is_published,
                    "source_version": row.source_version,
                    "created_by": row.created_by,
                }
                for row in rows
            ]

    async def archive_template(self, tenant_id: str, template_id: str) -> WorkflowTemplateRecord:
        async with self._session_factory() as session:
            async with session.begin():
                template_row = await self._get_template_row(session, tenant_id, template_id)
                template_row.status = "archived"
                template_row.archived_at = utc_now()
                template_row.updated_at = utc_now()
                await session.flush()
                return self._to_template_record(template_row)

    async def list_templates(self, tenant_id: str) -> list[WorkflowTemplateRecord]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(WorkflowTemplateTable)
                    .where(WorkflowTemplateTable.tenant_id == tenant_id)
                    .order_by(WorkflowTemplateTable.created_at, WorkflowTemplateTable.template_id)
                )
            ).scalars()
            return [self._to_template_record(row) for row in rows]

    async def list_workflow_summaries(
        self,
        *,
        tenant_id: str,
        workflow_id_prefix: str | None,
        name_query: str | None,
        limit: int,
        cursor: str | None,
    ) -> dict[str, object]:
        query = select(WorkflowTemplateTable).where(WorkflowTemplateTable.tenant_id == tenant_id)

        if workflow_id_prefix:
            query = query.where(WorkflowTemplateTable.template_id.startswith(workflow_id_prefix))

        if name_query:
            query = query.where(func.lower(WorkflowTemplateTable.name).contains(name_query.lower()))

        if cursor is not None:
            cursor_created_at, cursor_workflow_id = decode_workflow_list_cursor(cursor)
            query = query.where(
                or_(
                    WorkflowTemplateTable.created_at < cursor_created_at,
                    and_(
                        WorkflowTemplateTable.created_at == cursor_created_at,
                        WorkflowTemplateTable.template_id > cursor_workflow_id,
                    ),
                )
            )

        query = query.order_by(
            WorkflowTemplateTable.created_at.desc(),
            WorkflowTemplateTable.template_id.asc(),
        ).limit(limit + 1)

        async with self._session_factory() as session:
            rows = (await session.execute(query)).scalars().all()

        visible_rows = rows[:limit]
        next_cursor = None
        if len(rows) > limit:
            last_visible = visible_rows[-1]
            next_cursor = encode_workflow_list_cursor(
                created_at=last_visible.created_at,
                workflow_id=last_visible.template_id,
            )

        return {
            "items": [
                {
                    "workflow_id": row.template_id,
                    "tenant_id": row.tenant_id,
                    "name": row.name,
                    "status": row.status,
                    "latest_version": row.latest_version,
                }
                for row in visible_rows
            ],
            "next_cursor": next_cursor,
        }

    async def list_workflow_run_summaries(
        self,
        *,
        tenant_id: str,
        workflow_id: str | None,
        template_version: int | None,
        status: RunStatus | None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict[str, object]:
        query = (
            select(WorkflowRunLinkTable, RunTable)
            .join(RunTable, RunTable.run_id == WorkflowRunLinkTable.run_id)
            .where(WorkflowRunLinkTable.tenant_id == tenant_id, RunTable.tenant_id == tenant_id)
        )

        if workflow_id is not None:
            query = query.where(WorkflowRunLinkTable.template_id == workflow_id)

        if template_version is not None:
            query = query.where(WorkflowRunLinkTable.template_version == template_version)

        if status is not None:
            query = query.where(RunTable.status == status.value)

        if created_after is not None:
            query = query.where(RunTable.created_at >= created_after)

        if created_before is not None:
            query = query.where(RunTable.created_at <= created_before)

        if cursor is not None:
            cursor_created_at, cursor_run_id = decode_workflow_run_list_cursor(cursor)
            query = query.where(
                or_(
                    RunTable.created_at < cursor_created_at,
                    and_(
                        RunTable.created_at == cursor_created_at,
                        RunTable.run_id > cursor_run_id,
                    ),
                )
            )

        query = query.order_by(RunTable.created_at.desc(), RunTable.run_id.asc()).limit(limit + 1)

        async with self._session_factory() as session:
            rows = (await session.execute(query)).all()

        visible_rows = rows[:limit]
        next_cursor = None
        if len(rows) > limit:
            _, last_visible_run = visible_rows[-1]
            next_cursor = encode_workflow_run_list_cursor(
                created_at=last_visible_run.created_at,
                run_id=last_visible_run.run_id,
            )

        return {
            "items": [
                {
                    "run_id": run_row.run_id,
                    "tenant_id": link_row.tenant_id,
                    "template_id": link_row.template_id,
                    "template_name": link_row.template_name,
                    "template_version": link_row.template_version,
                    "started_at": run_row.created_at,
                    "status": run_row.status,
                    "error": run_row.error,
                    "last_updated_at": run_row.updated_at,
                }
                for link_row, run_row in visible_rows
            ],
            "next_cursor": next_cursor,
        }

    async def create_run_link(self, link: WorkflowRunLinkRecord) -> None:
        async with self._session_factory() as session:
            session.add(
                WorkflowRunLinkTable(
                    run_id=link.run_id,
                    tenant_id=link.tenant_id,
                    template_id=link.template_id,
                    template_version=link.template_version,
                    template_name=link.template_name,
                    launch_input=link.launch_input,
                    launch_metadata=link.launch_metadata,
                    effective_workflow_policy=link.effective_workflow_policy,
                    created_at=link.created_at,
                )
            )
            await session.commit()

    async def get_run_link(self, run_id: str) -> WorkflowRunLinkRecord | None:
        async with self._session_factory() as session:
            row = await session.get(WorkflowRunLinkTable, run_id)
            if row is None:
                return None
            return WorkflowRunLinkRecord(
                run_id=row.run_id,
                tenant_id=row.tenant_id,
                template_id=row.template_id,
                template_version=row.template_version,
                template_name=row.template_name,
                launch_input=row.launch_input,
                launch_metadata=row.launch_metadata,
                effective_workflow_policy=row.effective_workflow_policy,
                created_at=row.created_at,
            )

    @staticmethod
    def _to_template_record(row: WorkflowTemplateTable) -> WorkflowTemplateRecord:
        return WorkflowTemplateRecord(
            template_id=row.template_id,
            tenant_id=row.tenant_id,
            name=row.name,
            description=row.description,
            status=row.status,
            latest_version=row.latest_version,
            latest_published_version=row.latest_published_version,
            archived_at=row.archived_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _to_template_version_record(row: WorkflowTemplateVersionTable) -> WorkflowTemplateVersionRecord:
        return WorkflowTemplateVersionRecord(
            template_id=row.template_id,
            version=row.version,
            definition=row.definition,
            input_schema=row.input_schema,
            source_version=row.source_version,
            is_published=row.is_published,
            published_at=row.published_at,
            created_at=row.created_at,
            created_by=row.created_by,
        )

    @staticmethod
    async def _get_template_row(
        session: AsyncSession,
        tenant_id: str,
        template_id: str,
    ) -> WorkflowTemplateTable:
        return (
            await session.execute(
                select(WorkflowTemplateTable).where(
                    WorkflowTemplateTable.tenant_id == tenant_id,
                    WorkflowTemplateTable.template_id == template_id,
                )
            )
        ).scalar_one()

    @staticmethod
    async def _get_version_row(
        session: AsyncSession,
        tenant_id: str,
        template_id: str,
        version: int,
    ) -> WorkflowTemplateVersionTable:
        return (
            await session.execute(
                select(WorkflowTemplateVersionTable).where(
                    WorkflowTemplateVersionTable.tenant_id == tenant_id,
                    WorkflowTemplateVersionTable.template_id == template_id,
                    WorkflowTemplateVersionTable.version == version,
                )
            )
        ).scalar_one()

    @staticmethod
    async def _get_latest_draft_row(
        session: AsyncSession,
        tenant_id: str,
        template_id: str,
    ) -> WorkflowTemplateVersionTable | None:
        return (
            await session.execute(
                select(WorkflowTemplateVersionTable)
                .where(
                    WorkflowTemplateVersionTable.tenant_id == tenant_id,
                    WorkflowTemplateVersionTable.template_id == template_id,
                    WorkflowTemplateVersionTable.is_published.is_(False),
                )
                .order_by(WorkflowTemplateVersionTable.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
