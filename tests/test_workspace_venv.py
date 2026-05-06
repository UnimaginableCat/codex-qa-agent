from __future__ import annotations

from pathlib import Path
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

    def test_execution_payload_reports_error_workspace_venv_error(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            exc = WorkspaceVenvError(
                current_executable=root.parent / "bin" / "python3",
                workspace_root=root,
                expected_prefixes=(root / ".venv314", root / ".venv"),
            )

            payload = workspace_venv_error_payload(exc, payload_kind="execution_result")

        self.assertEqual(payload["status"], "ERROR")
        details = payload["details"]
        self.assertIsInstance(details, dict)
        self.assertEqual(details["code"], "workspace_venv_required")
        self.assertEqual(details["workspace_root"], str(root))


if __name__ == "__main__":
    unittest.main()
