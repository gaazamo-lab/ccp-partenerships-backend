"""Per-module demo datasets, ported from the frontend mock seeds.

Each module file exposes ``async def seed(session)``. It must be idempotent (check for its own
marker rows first) and must not commit; ``scripts.seed`` owns the transaction.
"""

from __future__ import annotations

import importlib

# Order matters: later modules may look up stakeholders created by `crm`.
MODULES = ["crm", "kol", "consultations", "microsites", "international", "travel"]


async def seed_all(session) -> None:
    for name in MODULES:
        try:
            module = importlib.import_module(f"scripts.demo.{name}")
        except ModuleNotFoundError as exc:
            if exc.name != f"scripts.demo.{name}":
                raise
            continue
        await module.seed(session)
        await session.flush()
