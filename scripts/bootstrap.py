# scripts/bootstrap.py
# Idempotent DB provisioning for the AI's own concern.
# Connects as the postgres superuser (BOOTSTRAP_DATABASE_URL) and creates the
# AI's migration + runtime roles, the `ai` schema, ownership, and default grants.
# Grants NO access to the public schema — the AI fetches API data over HTTP.
#
# Identifiers and the password literal are quoted server-side via
# quote_ident() / quote_literal(), so special characters cannot break the DDL.
import asyncio
import os
from urllib.parse import unquote, urlparse

import asyncpg


def _plain_dsn(url: str) -> str:
    # asyncpg wants a plain postgres:// DSN, not the SQLAlchemy +asyncpg form.
    return url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgres+asyncpg://", "postgresql://"
    )


def _conn_info(url: str) -> tuple[str, str, str]:
    p = urlparse(_plain_dsn(url))
    return (
        unquote(p.username or ""),
        unquote(p.password or ""),
        unquote((p.path or "").lstrip("/")),
    )


async def main() -> None:
    bootstrap_url = os.environ["BOOTSTRAP_DATABASE_URL"]
    runtime_user, runtime_pw, runtime_db = _conn_info(os.environ["DATABASE_URL"])
    migrator_user, migrator_pw, migrator_db = _conn_info(
        os.environ["MIGRATIONS_DATABASE_URL"]
    )
    _, _, database = _conn_info(bootstrap_url)

    if runtime_db != database or migrator_db != database:
        raise SystemExit(
            "all three DATABASE URLs must reference the same database "
            f"(bootstrap={database}, runtime={runtime_db}, migrations={migrator_db})"
        )

    conn = await asyncpg.connect(_plain_dsn(bootstrap_url))
    try:

        async def ident(name: str) -> str:
            return await conn.fetchval("SELECT quote_ident($1)", name)

        async def literal(value: str) -> str:
            return await conn.fetchval("SELECT quote_literal($1)", value)

        for user, pw in ((migrator_user, migrator_pw), (runtime_user, runtime_pw)):
            role_ident = await ident(user)
            pw_literal = await literal(pw)
            exists = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = $1)", user
            )
            verb = "ALTER" if exists else "CREATE"
            await conn.execute(f"{verb} ROLE {role_ident} LOGIN PASSWORD {pw_literal}")

        migrator_ident = await ident(migrator_user)
        runtime_ident = await ident(runtime_user)

        await conn.execute(
            f"CREATE SCHEMA IF NOT EXISTS ai AUTHORIZATION {migrator_ident}"
        )
        await conn.execute(f"GRANT USAGE ON SCHEMA ai TO {runtime_ident}")
        await conn.execute(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {migrator_ident} IN SCHEMA ai "
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {runtime_ident}"
        )
        await conn.execute(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {migrator_ident} IN SCHEMA ai "
            f"GRANT USAGE, SELECT ON SEQUENCES TO {runtime_ident}"
        )
        await conn.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA ai TO {runtime_ident}"
        )
        await conn.execute(
            f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA ai TO {runtime_ident}"
        )
        print(
            "AI bootstrap complete: ai schema, roles, grants ensured (no public access)."
        )
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
