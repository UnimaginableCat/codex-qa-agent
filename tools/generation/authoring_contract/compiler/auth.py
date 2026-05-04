"""Auth strategy resolution for authoring compilation."""

from __future__ import annotations

from ..models import AuthoringPlan


def resolve_auth_strategy(
    *,
    explicit_auth_strategy: list[str],
    authoring_plan: AuthoringPlan,
) -> list[str]:
    if explicit_auth_strategy:
        return list(explicit_auth_strategy)
    if authoring_plan.defaults.auth.strip():
        return [authoring_plan.defaults.auth.strip()]
    return []
