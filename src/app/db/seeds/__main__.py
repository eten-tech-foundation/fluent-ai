"""Run all seeds: ``uv run python -m app.db.seeds``."""

import asyncio

from app.db.seeds.runner import run_all_seeds


if __name__ == "__main__":
    asyncio.run(run_all_seeds())
