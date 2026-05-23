from sqlalchemy import text
from weakref import WeakKeyDictionary

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from agent_runtime.state.tables import (
    AssistantMessageTable,
    AssistantRunLinkTable,
    AssistantSessionTable,
    Base,
)

_SESSION_FACTORY_ENGINES: WeakKeyDictionary[async_sessionmaker[AsyncSession], AsyncEngine] = WeakKeyDictionary()


def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
    del connection_record
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def build_engine(db_url: str) -> AsyncEngine:
    engine = create_async_engine(db_url, future=True)
    event.listen(engine.sync_engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def build_session_factory(db_url: str) -> async_sessionmaker[AsyncSession]:
    engine = build_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    _SESSION_FACTORY_ENGINES[session_factory] = engine
    return session_factory


async def dispose_session_factory(session_factory: async_sessionmaker[AsyncSession]) -> None:
    engine = _SESSION_FACTORY_ENGINES.pop(session_factory, None)
    if engine is None:
        return
    await engine.dispose()


async def init_db(session_factory: async_sessionmaker[AsyncSession]) -> None:
    engine = _SESSION_FACTORY_ENGINES.get(session_factory)
    if engine is None:
        raise RuntimeError("session factory is not registered with an engine")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.run_sync(_ensure_assistant_tables)
        await _upgrade_workflow_templates_v2_columns(connection)
        await _upgrade_workflow_template_versions_v2_columns(connection)
        await _upgrade_workflow_run_links_launch_metadata(connection)


def _ensure_assistant_tables(connection) -> None:
    AssistantSessionTable.__table__.create(bind=connection, checkfirst=True)
    AssistantMessageTable.__table__.create(bind=connection, checkfirst=True)
    AssistantRunLinkTable.__table__.create(bind=connection, checkfirst=True)


async def _get_table_column_names(connection, table_name: str) -> set[str]:
    result = await connection.execute(text(f"PRAGMA table_info({table_name})"))
    return {row[1] for row in result}


async def _upgrade_workflow_templates_v2_columns(connection) -> None:
    column_names = await _get_table_column_names(connection, "workflow_templates")
    latest_published_version_added = False
    if "latest_published_version" not in column_names:
        await connection.execute(
            text("ALTER TABLE workflow_templates ADD COLUMN latest_published_version INTEGER")
        )
        latest_published_version_added = True
    if "archived_at" not in column_names:
        await connection.execute(text("ALTER TABLE workflow_templates ADD COLUMN archived_at TEXT"))
    if latest_published_version_added:
        await _backfill_workflow_templates_latest_published_version(connection)


async def _upgrade_workflow_template_versions_v2_columns(connection) -> None:
    column_names = await _get_table_column_names(connection, "workflow_template_versions")
    if "source_version" in column_names:
        return
    await connection.execute(text("ALTER TABLE workflow_template_versions ADD COLUMN source_version INTEGER"))


async def _backfill_workflow_templates_latest_published_version(connection) -> None:
    await connection.execute(
        text(
            """
            UPDATE workflow_templates
            SET latest_published_version = (
                SELECT MAX(version)
                FROM workflow_template_versions
                WHERE workflow_template_versions.tenant_id = workflow_templates.tenant_id
                  AND workflow_template_versions.template_id = workflow_templates.template_id
                  AND workflow_template_versions.is_published = 1
            )
            WHERE latest_published_version IS NULL
              AND EXISTS (
                SELECT 1
                FROM workflow_template_versions
                WHERE workflow_template_versions.tenant_id = workflow_templates.tenant_id
                  AND workflow_template_versions.template_id = workflow_templates.template_id
                  AND workflow_template_versions.is_published = 1
              )
            """
        )
    )


async def _upgrade_workflow_run_links_launch_metadata(connection) -> None:
    column_names = await _get_table_column_names(connection, "workflow_run_links")
    if "launch_metadata" in column_names:
        return
    await connection.execute(
        text("ALTER TABLE workflow_run_links ADD COLUMN launch_metadata JSON NOT NULL DEFAULT '{}' ")
    )
