from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_runtime.assistant.models import (
    AssistantMessageRecord,
    AssistantRunLinkRecord,
    AssistantSessionRecord,
)
from agent_runtime.state.tables import (
    AssistantMessageTable,
    AssistantRunLinkTable,
    AssistantSessionTable,
    RunTable,
)


class AssistantRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_session(self, record: AssistantSessionRecord) -> AssistantSessionRecord:
        async with self._session_factory() as session:
            session.add(
                AssistantSessionTable(
                    session_id=record.session_id,
                    tenant_id=record.tenant_id,
                    title=record.title,
                    mode=record.mode,
                    status=record.status,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                )
            )
            await session.commit()
        return record

    async def list_sessions(self, tenant_id: str) -> list[AssistantSessionRecord]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(AssistantSessionTable)
                    .where(AssistantSessionTable.tenant_id == tenant_id)
                    .order_by(AssistantSessionTable.created_at, AssistantSessionTable.session_id)
                )
            ).scalars()
            return [self._map_session(row) for row in rows]

    async def get_session(self, tenant_id: str, session_id: str) -> AssistantSessionRecord | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(AssistantSessionTable).where(
                    AssistantSessionTable.tenant_id == tenant_id,
                    AssistantSessionTable.session_id == session_id,
                )
            )
            if row is None:
                return None
            return self._map_session(row)

    async def add_message(self, record: AssistantMessageRecord) -> AssistantMessageRecord:
        async with self._session_factory() as session:
            async with session.begin():
                parent_session = await session.get(AssistantSessionTable, record.session_id)
                if parent_session is None:
                    raise RuntimeError(f"assistant session not found: {record.session_id}")
                if parent_session.tenant_id != record.tenant_id:
                    raise RuntimeError(
                        f"assistant session tenant mismatch for {record.session_id}: {record.tenant_id}"
                    )
                if record.run_id is not None:
                    run = await session.get(RunTable, record.run_id)
                    if run is None:
                        raise RuntimeError(f"assistant run not found: {record.run_id}")
                    if run.tenant_id != parent_session.tenant_id:
                        raise RuntimeError(
                            f"assistant run tenant mismatch for {record.run_id}: {parent_session.tenant_id}"
                        )

                session.add(
                    AssistantMessageTable(
                        message_id=record.message_id,
                        session_id=record.session_id,
                        tenant_id=record.tenant_id,
                        role=record.role,
                        content=record.content,
                        structured_payload=record.structured_payload,
                        run_id=record.run_id,
                        created_at=record.created_at,
                    )
                )
                if parent_session.updated_at < record.created_at:
                    parent_session.updated_at = record.created_at
        return record

    async def list_messages(self, tenant_id: str, session_id: str) -> list[AssistantMessageRecord]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(AssistantMessageTable)
                    .where(
                        AssistantMessageTable.tenant_id == tenant_id,
                        AssistantMessageTable.session_id == session_id,
                    )
                    .order_by(AssistantMessageTable.created_at, AssistantMessageTable.message_id)
                )
            ).scalars()
            return [self._map_message(row) for row in rows]

    async def create_run_link(self, record: AssistantRunLinkRecord) -> AssistantRunLinkRecord:
        async with self._session_factory() as session:
            async with session.begin():
                parent_session = await session.get(AssistantSessionTable, record.session_id)
                if parent_session is None:
                    raise RuntimeError(f"assistant session not found: {record.session_id}")

                message = await session.get(AssistantMessageTable, record.message_id)
                if message is None:
                    raise RuntimeError(f"assistant message not found: {record.message_id}")
                if message.session_id != record.session_id:
                    raise RuntimeError(
                        f"assistant message session mismatch for {record.message_id}: {record.session_id}"
                    )
                if message.tenant_id != parent_session.tenant_id:
                    raise RuntimeError(
                        f"assistant message tenant mismatch for {record.message_id}: {parent_session.tenant_id}"
                    )
                run = await session.get(RunTable, record.run_id)
                if run is None:
                    raise RuntimeError(f"assistant run not found: {record.run_id}")
                if run.tenant_id != parent_session.tenant_id:
                    raise RuntimeError(
                        f"assistant run tenant mismatch for {record.run_id}: {parent_session.tenant_id}"
                    )

                session.add(
                    AssistantRunLinkTable(
                        link_id=record.link_id,
                        session_id=record.session_id,
                        message_id=record.message_id,
                        run_id=record.run_id,
                        launch_kind=record.launch_kind,
                        created_at=record.created_at,
                    )
                )
                if parent_session.updated_at < record.created_at:
                    parent_session.updated_at = record.created_at
        return record

    async def list_run_links(self, tenant_id: str, session_id: str) -> list[AssistantRunLinkRecord]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(AssistantRunLinkTable)
                    .join(
                        AssistantSessionTable,
                        AssistantSessionTable.session_id == AssistantRunLinkTable.session_id,
                    )
                    .where(
                        AssistantSessionTable.tenant_id == tenant_id,
                        AssistantRunLinkTable.session_id == session_id,
                    )
                    .order_by(AssistantRunLinkTable.created_at, AssistantRunLinkTable.link_id)
                )
            ).scalars()
            return [self._map_run_link(row) for row in rows]

    @staticmethod
    def _map_session(row: AssistantSessionTable) -> AssistantSessionRecord:
        return AssistantSessionRecord(
            session_id=row.session_id,
            tenant_id=row.tenant_id,
            title=row.title,
            mode=row.mode,
            status=row.status,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _map_message(row: AssistantMessageTable) -> AssistantMessageRecord:
        return AssistantMessageRecord(
            message_id=row.message_id,
            session_id=row.session_id,
            tenant_id=row.tenant_id,
            role=row.role,
            content=row.content,
            structured_payload=row.structured_payload,
            run_id=row.run_id,
            created_at=row.created_at,
        )

    @staticmethod
    def _map_run_link(row: AssistantRunLinkTable) -> AssistantRunLinkRecord:
        return AssistantRunLinkRecord(
            link_id=row.link_id,
            session_id=row.session_id,
            message_id=row.message_id,
            run_id=row.run_id,
            launch_kind=row.launch_kind,
            created_at=row.created_at,
        )
