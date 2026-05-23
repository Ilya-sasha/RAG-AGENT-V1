from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from agent_runtime.assistant.models import (
    AssistantMessageRecord,
    AssistantRunLinkRecord,
    AssistantSessionRecord,
)
from agent_runtime.assistant.repository import AssistantRepository
from agent_runtime.domain.models import RunRecord
from agent_runtime.state.db import build_session_factory, dispose_session_factory, init_db
from agent_runtime.state.repositories import RuntimeRepository


@pytest.mark.asyncio
async def test_add_message_updates_session_updated_at(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)
        repository = AssistantRepository(session_factory)
        created_at = datetime(2026, 5, 19, 10, 0, tzinfo=UTC)
        session_record = AssistantSessionRecord(
            tenant_id="tenant-a",
            title="Chat A",
            mode="chat",
            created_at=created_at,
            updated_at=created_at,
        )
        await repository.create_session(session_record)

        message_time = created_at + timedelta(minutes=5)
        await repository.add_message(
            AssistantMessageRecord(
                tenant_id="tenant-a",
                session_id=session_record.session_id,
                role="user",
                content="hello",
                created_at=message_time,
            )
        )

        fresh_session = await repository.get_session("tenant-a", session_record.session_id)

        assert fresh_session is not None
        assert fresh_session.updated_at == message_time
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_add_message_with_tenant_session_mismatch_raises(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)
        repository = AssistantRepository(session_factory)
        session_record = AssistantSessionRecord(
            tenant_id="tenant-a",
            title="Chat A",
            mode="chat",
        )
        await repository.create_session(session_record)

        with pytest.raises(RuntimeError, match="assistant session tenant mismatch"):
            await repository.add_message(
                AssistantMessageRecord(
                    tenant_id="tenant-b",
                    session_id=session_record.session_id,
                    role="user",
                    content="hello",
                )
            )
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_add_message_with_cross_tenant_run_raises(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)
        assistant_repository = AssistantRepository(session_factory)
        runtime_repository = RuntimeRepository(session_factory)
        session_record = AssistantSessionRecord(
            tenant_id="tenant-a",
            title="Chat A",
            mode="chat",
        )
        await assistant_repository.create_session(session_record)
        run = RunRecord(
            tenant_id="tenant-b",
            objective="Investigate incident",
        )
        from agent_runtime.domain.enums import AgentRole
        from agent_runtime.domain.models import AgentRecord

        supervisor = AgentRecord(
            run_id=run.run_id,
            role=AgentRole.SUPERVISOR,
            objective=run.objective,
        )
        await runtime_repository.create_run(run, supervisor)

        with pytest.raises(RuntimeError, match="assistant run tenant mismatch"):
            await assistant_repository.add_message(
                AssistantMessageRecord(
                    tenant_id="tenant-a",
                    session_id=session_record.session_id,
                    role="user",
                    content="hello",
                    run_id=run.run_id,
                )
            )
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_create_run_link_with_mismatched_session_and_message_raises(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)
        assistant_repository = AssistantRepository(session_factory)
        runtime_repository = RuntimeRepository(session_factory)
        session_a = AssistantSessionRecord(
            tenant_id="tenant-a",
            title="Chat A",
            mode="task",
        )
        session_b = AssistantSessionRecord(
            tenant_id="tenant-a",
            title="Chat B",
            mode="task",
        )
        await assistant_repository.create_session(session_a)
        await assistant_repository.create_session(session_b)

        message = await assistant_repository.add_message(
            AssistantMessageRecord(
                tenant_id="tenant-a",
                session_id=session_a.session_id,
                role="user",
                content="launch task",
            )
        )
        run = RunRecord(
            tenant_id="tenant-a",
            objective="Investigate incident",
        )
        # Keep the runtime row valid with the smallest possible persisted run graph.
        from agent_runtime.domain.enums import AgentRole
        from agent_runtime.domain.models import AgentRecord

        supervisor = AgentRecord(
            run_id=run.run_id,
            role=AgentRole.SUPERVISOR,
            objective=run.objective,
        )
        await runtime_repository.create_run(run, supervisor)

        with pytest.raises(RuntimeError, match="assistant message session mismatch"):
            await assistant_repository.create_run_link(
                AssistantRunLinkRecord(
                    session_id=session_b.session_id,
                    message_id=message.message_id,
                    run_id=run.run_id,
                    launch_kind="task",
                )
            )
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_create_run_link_with_cross_tenant_run_raises(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)
        assistant_repository = AssistantRepository(session_factory)
        runtime_repository = RuntimeRepository(session_factory)
        session_record = AssistantSessionRecord(
            tenant_id="tenant-a",
            title="Task A",
            mode="task",
        )
        await assistant_repository.create_session(session_record)
        message = await assistant_repository.add_message(
            AssistantMessageRecord(
                tenant_id="tenant-a",
                session_id=session_record.session_id,
                role="user",
                content="launch task",
            )
        )
        run = RunRecord(
            tenant_id="tenant-b",
            objective="Investigate incident",
        )
        from agent_runtime.domain.enums import AgentRole
        from agent_runtime.domain.models import AgentRecord

        supervisor = AgentRecord(
            run_id=run.run_id,
            role=AgentRole.SUPERVISOR,
            objective=run.objective,
        )
        await runtime_repository.create_run(run, supervisor)

        with pytest.raises(RuntimeError, match="assistant run tenant mismatch"):
            await assistant_repository.create_run_link(
                AssistantRunLinkRecord(
                    session_id=session_record.session_id,
                    message_id=message.message_id,
                    run_id=run.run_id,
                    launch_kind="task",
                )
            )
    finally:
        await dispose_session_factory(session_factory)


@pytest.mark.asyncio
async def test_create_run_link_updates_session_updated_at(tmp_path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}"
    session_factory = build_session_factory(db_url)
    try:
        await init_db(session_factory)
        assistant_repository = AssistantRepository(session_factory)
        runtime_repository = RuntimeRepository(session_factory)
        created_at = datetime(2026, 5, 19, 11, 0, tzinfo=UTC)
        session_record = AssistantSessionRecord(
            tenant_id="tenant-a",
            title="Task A",
            mode="task",
            created_at=created_at,
            updated_at=created_at,
        )
        await assistant_repository.create_session(session_record)
        message = await assistant_repository.add_message(
            AssistantMessageRecord(
                tenant_id="tenant-a",
                session_id=session_record.session_id,
                role="user",
                content="launch task",
                created_at=created_at,
            )
        )
        run = RunRecord(
            tenant_id="tenant-a",
            objective="Investigate incident",
        )
        from agent_runtime.domain.enums import AgentRole
        from agent_runtime.domain.models import AgentRecord

        supervisor = AgentRecord(
            run_id=run.run_id,
            role=AgentRole.SUPERVISOR,
            objective=run.objective,
        )
        await runtime_repository.create_run(run, supervisor)

        link_time = created_at + timedelta(minutes=7)
        await assistant_repository.create_run_link(
            AssistantRunLinkRecord(
                session_id=session_record.session_id,
                message_id=message.message_id,
                run_id=run.run_id,
                launch_kind="task",
                created_at=link_time,
            )
        )

        fresh_session = await assistant_repository.get_session("tenant-a", session_record.session_id)

        assert fresh_session is not None
        assert fresh_session.updated_at == link_time
    finally:
        await dispose_session_factory(session_factory)
