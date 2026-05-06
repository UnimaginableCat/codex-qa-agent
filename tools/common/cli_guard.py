"""Shared guards for command-line entrypoints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from .runtime import WorkspaceVenvError, ensure_workspace_venv


PayloadKind = Literal["execution_result", "generation"]


def bootstrap_workspace_cli(module_file: str, *, payload_kind: PayloadKind) -> Path:
    """Resolve the workspace root from a tool module and enforce workspace venv execution."""

    workspace_root = Path(module_file).resolve().parents[2]
    enforce_workspace_venv_or_exit(workspace_root=workspace_root, payload_kind=payload_kind)
    return workspace_root


def enforce_workspace_venv_or_exit(
    *,
    workspace_root: Path,
    payload_kind: PayloadKind,
) -> None:
    """Exit with structured JSON unless the current interpreter is a workspace venv."""

    try:
        ensure_workspace_venv(workspace_root=workspace_root)
    except WorkspaceVenvError as exc:
        print(json.dumps(workspace_venv_error_payload(exc, payload_kind=payload_kind), ensure_ascii=False))
        raise SystemExit(1) from None


def workspace_venv_error_payload(exc: WorkspaceVenvError, *, payload_kind: PayloadKind) -> dict[str, object]:
    details = {
        "code": "workspace_venv_required",
        "current_executable": str(exc.current_executable),
        "current_prefix": str(exc.current_prefix) if exc.current_prefix is not None else None,
        "virtual_env": str(exc.virtual_env) if exc.virtual_env is not None else None,
        "workspace_root": str(exc.workspace_root),
        "expected_prefixes": [str(path) for path in exc.expected_prefixes],
    }
    if payload_kind == "generation":
        return {
            "status": "BLOCKED",
            "message": str(exc),
            "diagnostics": [
                {
                    "code": "workspace_venv_required",
                    "message": str(exc),
                    "severity": "ERROR",
                    "details": details,
                }
            ],
            "artifact_paths": {},
        }
    return {
        "status": "BLOCKED",
        "message": str(exc),
        "details": details,
    }
