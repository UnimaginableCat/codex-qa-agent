from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from tools.common.cli_guard import workspace_venv_error_payload
from tools.common.runtime import WorkspaceVenvError, ensure_workspace_venv


class WorkspaceVenvGuardTests(unittest.TestCase):
    def test_accepts_workspace_root_venv_interpreter(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            executable = root / ".venv314" / "Scripts" / "python.exe"

            ensure_workspace_venv(workspace_root=root, executable=str(executable))

    def test_accepts_workspace_root_posix_venv_interpreter(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            executable = root / ".venv" / "bin" / "python"

            ensure_workspace_venv(workspace_root=root, executable=str(executable))

    def test_accepts_uv_symlinked_workspace_venv_by_runtime_prefix(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            external_executable = root.parent / "uv" / "python" / "cpython-3.14" / "bin" / "python3.14"
            workspace_prefix = root / ".venv"

            ensure_workspace_venv(
                workspace_root=root,
                executable=str(external_executable),
                sys_prefix=str(workspace_prefix),
            )

    def test_rejects_external_prefix_even_when_virtual_env_env_var_points_to_workspace(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            external_executable = root.parent / "bin" / "python3"
            external_prefix = root.parent / "system-python"

            with self.assertRaises(WorkspaceVenvError):
                ensure_workspace_venv(
                    workspace_root=root,
                    executable=str(external_executable),
                    sys_prefix=str(external_prefix),
                    virtual_env=str(root / ".venv"),
                )

    def test_rejects_project_venv_under_code(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            executable = root / "code" / "beck-end-1.0" / ".venv311" / "Scripts" / "python.exe"

            with self.assertRaises(WorkspaceVenvError):
                ensure_workspace_venv(workspace_root=root, executable=str(executable))

    def test_rejects_system_python_outside_workspace_venv(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            executable = root.parent / "bin" / "python3"

            with self.assertRaises(WorkspaceVenvError) as captured:
                ensure_workspace_venv(workspace_root=root, executable=str(executable))

        self.assertEqual(captured.exception.workspace_root, root.resolve())
        self.assertTrue(any(path.name == ".venv314" for path in captured.exception.expected_prefixes))

    def test_generation_payload_reports_blocked_workspace_venv_error(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            exc = WorkspaceVenvError(
                current_executable=root.parent / "bin" / "python3",
                current_prefix=root.parent / "system-python",
                workspace_root=root,
                expected_prefixes=(root / ".venv314", root / ".venv"),
            )

            payload = workspace_venv_error_payload(exc, payload_kind="generation")

        self.assertEqual(payload["status"], "BLOCKED")
        diagnostics = payload["diagnostics"]
        self.assertIsInstance(diagnostics, list)
        diagnostic = diagnostics[0]
        self.assertIsInstance(diagnostic, dict)
        self.assertEqual(diagnostic["code"], "workspace_venv_required")
        self.assertEqual(diagnostic["details"]["workspace_root"], str(root))
        self.assertEqual(diagnostic["details"]["current_prefix"], str(root.parent / "system-python"))

    def test_execution_payload_reports_blocked_workspace_venv_error(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            exc = WorkspaceVenvError(
                current_executable=root.parent / "bin" / "python3",
                workspace_root=root,
                expected_prefixes=(root / ".venv314", root / ".venv"),
            )

            payload = workspace_venv_error_payload(exc, payload_kind="execution_result")

        self.assertEqual(payload["status"], "BLOCKED")
        details = payload["details"]
        self.assertIsInstance(details, dict)
        self.assertEqual(details["code"], "workspace_venv_required")
        self.assertEqual(details["workspace_root"], str(root))

    def test_scenario_runner_package_initializer_is_lightweight(self) -> None:
        script = (
            "import json, sys\n"
            "import tools.scenario_runner\n"
            "print(json.dumps({\n"
            "    'orchestration': 'tools.scenario_runner.orchestration' in sys.modules,\n"
            "    'runtime': 'tools.scenario_runner.runtime' in sys.modules,\n"
            "    'parser': 'tools.scenario_runner.parser' in sys.modules,\n"
            "}))\n"
        )

        completed = subprocess.run(  # noqa: S603
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)

        self.assertFalse(payload["orchestration"])
        self.assertFalse(payload["runtime"])
        self.assertFalse(payload["parser"])

    def test_generation_package_initializer_is_lightweight(self) -> None:
        script = (
            "import json, sys\n"
            "import tools.generation\n"
            "print(json.dumps({\n"
            "    'authoring': 'tools.generation.authoring' in sys.modules,\n"
            "    'application': 'tools.generation.application' in sys.modules,\n"
            "    'review': 'tools.generation.review' in sys.modules,\n"
            "}))\n"
        )

        completed = subprocess.run(  # noqa: S603
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)

        self.assertFalse(payload["authoring"])
        self.assertFalse(payload["application"])
        self.assertFalse(payload["review"])


if __name__ == "__main__":
    unittest.main()
