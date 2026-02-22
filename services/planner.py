# services/planner.py

"""Deprecated compatibility shim for planner orchestration.

Canonical planning orchestration now lives in ``agents.planning``.
Keep this module only for backwards-compatible imports while callers migrate.
"""

from __future__ import annotations

import warnings
from uuid import UUID

from agents.planning import (
    PlannerError,
    close_planner_client as _close_planner_client,
    generate_group_plans as _generate_group_plans,
    init_planner_client as _init_planner_client,
)

_DEPRECATION_MSG = (
    "services.planner is deprecated; import planner orchestration from "
    "agents.planning instead."
)


def _warn_deprecated() -> None:
    warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)


async def init_planner_client() -> None:
    _warn_deprecated()
    await _init_planner_client()


async def close_planner_client() -> None:
    _warn_deprecated()
    await _close_planner_client()


async def generate_group_plans(
    group_id: UUID,
    refinement_notes: str | None = None,
) -> list[dict[str, object]]:
    _warn_deprecated()
    return await _generate_group_plans(group_id=group_id, refinement_notes=refinement_notes)


__all__ = [
    "PlannerError",
    "init_planner_client",
    "close_planner_client",
    "generate_group_plans",
]
