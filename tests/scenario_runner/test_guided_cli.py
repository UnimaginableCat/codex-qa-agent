from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.common.statuses import StepStatus
from tools.scenario_runner.cli import main as cli_main
from tools.scenario_runner.domain.pause import RunContinuationState


class GuidedCliTests(unittest.TestCase):
    def test_guided_run_outputs_operator_state_for_pause(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            scenario_path = self._prepare_workspace(root)

            exit_code, payload = self._run_cli(root, ["--scenario", str(scenario_path), "--mode", "guided"])
            operator_state = payload["operator_state"]

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["summary"]["final_status"], StepStatus.BLOCKED.value)
        self.assertEqual(operator_state["run_mode"], "guided")
        self.assertEqual(operator_state["continuation_state"], RunContinuationState.PAUSED.value)
        self.assertTrue(operator_state["resumable"])
        self.assertIsNotNone(operator_state["active_decision_point"])
        self.assertEqual(
            [action["action_id"] for action in operator_state["available_actions"]],
            ["continue_if_fixed", "skip_step", "abort_run"],
        )
        self.assertEqual(operator_state["required_inputs"][0]["name"], "action_id")
        self.assertTrue(operator_state["resume_instructions"])

    def test_inspect_pause_outputs_pending_decision(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            scenario_path = self._prepare_workspace(root)
            _, guided_payload = self._run_cli(root, ["--scenario", str(scenario_path), "--mode", "guided"])
            pause_state_path = guided_payload["operator_state"]["pause_state_path"]

            exit_code, payload = self._run_cli(root, ["--inspect-pause", pause_state_path])
            operator_state = payload["operator_state"]

        self.assertEqual(exit_code, 0)
        self.assertEqual(operator_state["continuation_state"], RunContinuationState.PAUSED.value)
        self.assertEqual(operator_state["recommended_action_id"], "continue_if_fixed")
        self.assertEqual(operator_state["active_decision_point"]["continuation_policy"], "wait_for_decision")
        self.assertEqual(operator_state["run_termination"]["kind"], "paused")
        self.assertIn("available_actions", operator_state)

    def test_resume_with_selected_action_uses_pause_resume_contracts(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            scenario_path = self._prepare_workspace(root)
            _, guided_payload = self._run_cli(root, ["--scenario", str(scenario_path), "--mode", "guided"])
            pause_state_path = guided_payload["operator_state"]["pause_state_path"]

            exit_code, payload = self._run_cli(root, ["--resume", pause_state_path, "--action", "abort_run"])
            summary = payload["summary"]
            operator_state = payload["operator_state"]
            pause_payload = json.loads(Path(pause_state_path).read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 1)
        self.assertEqual(summary["decision_resolution"]["selected_action"]["action_id"], "abort_run")
        self.assertEqual(summary["details"]["run_termination"]["kind"], "aborted")
        self.assertEqual(operator_state["run_mode"], "guided")
        self.assertFalse(operator_state["resumable"])
        self.assertFalse(pause_payload["active"])

    def test_auto_mode_preserves_legacy_top_level_summary_payload(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            scenario_path = self._prepare_workspace(root, tool_status="PASS")

            exit_code, payload = self._run_cli(root, ["--scenario", str(scenario_path)])

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["final_status"], StepStatus.PASS.value)
        self.assertEqual(payload["details"]["run_mode"], "auto")
        self.assertNotIn("operator_state", payload)

    @staticmethod
    def _run_cli(root: Path, argv: list[str]) -> tuple[int, dict]:
        previous_cwd = Path.cwd()
        output = io.StringIO()
        try:
            os.chdir(root)
            with patch("tools.scenario_runner.orchestration.preflight.importlib.util.find_spec", return_value=object()):
                with redirect_stdout(output):
                    exit_code = cli_main(argv)
        finally:
            os.chdir(previous_cwd)
        return exit_code, json.loads(output.getvalue())

    @staticmethod
    def _prepare_workspace(root: Path, *, tool_status: str = "FAIL") -> Path:
        (root / "code" / "demo-project").mkdir(parents=True, exist_ok=True)
        (root / "env").mkdir(parents=True, exist_ok=True)
        (root / "env" / "demo.env").write_text("API_BASE_URL=http://localhost\n", encoding="utf-8")
        api_tool = root / "tools" / "api" / "run_request.py"
        api_tool.parent.mkdir(parents=True, exist_ok=True)
        api_tool.write_text(
            "\n".join(
                [
                    "import json",
                    f"print(json.dumps({{'status': '{tool_status}', 'message': 'fake {tool_status.lower()}', 'response': {{'body': {{'id': 123}}}}}}))",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        scenario_path = root / "scenario.md"
        scenario_path.write_text(
            "\n".join(
                [
                    "# Scenario: Guided CLI",
                    "",
                    "## Project",
                    "code/demo-project",
                    "",
                    "## Environment",
                    "env/demo.env",
                    "",
                    "## Steps",
                    "",
                    "### Step 1",
                    "Type: api",
                    "Name: create",
                    "Method: POST",
                    "Path: /items",
                    "Capture:",
                    "- response.body.id -> item_id",
                    "",
                    "### Step 2",
                    "Type: api",
                    "Name: read",
                    "Method: GET",
                    "Path: /items/{{item_id}}",
                ]
            ),
            encoding="utf-8",
        )
        return scenario_path


if __name__ == "__main__":
    unittest.main()
