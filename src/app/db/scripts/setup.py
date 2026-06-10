"""Fluent AI database setup: migrations + seeds."""

import asyncio
import subprocess
import sys

from app.db.seeds.runner import run_all_seeds


def setup() -> None:
    print("=== Fluent AI DB Setup ===\n")

    print("[1/2] Running migrations...")
    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        capture_output=False,
        text=True,
    )
    if result.returncode != 0:
        sys.exit(result.returncode)
    print("Migrations complete.\n")

    print("[2/2] Running seeds...")
    asyncio.run(run_all_seeds())
    print("\nSeeds complete.\n")

    print("=== Setup complete ===")


if __name__ == "__main__":
    setup()
