"""Support code for the generation CLI adapter."""

from __future__ import annotations

import json
from typing import Any

from tools.common.json_safe import to_json_safe
from tools.common.statuses import StepStatus
from tools.generation.domain.models import GenerationDiagnostic


def _error_payload(diagnostics: list[GenerationDiagnostic]) -> dict[str, Any]:
    return to_json_safe(
        {
            "status": StepStatus.BLOCKED.value,
            "message": "Generation adapter request is blocked by input or staged-validation diagnostics.",
            "diagnostics": [diagnostic.to_dict() for diagnostic in diagnostics],
            "artifact_paths": {},
        }
    )



def _print_payload(payload: dict[str, Any], *, output_format: str = "json", workflow: str = "generation") -> None:
    if output_format == "text" and workflow == "authoring":
        print(_render_authoring_text(payload))
        return
    if output_format == "text" and workflow == "generation":
        print(_render_generation_text(payload))
        return
    if output_format == "text" and workflow == "review":
        print(_render_review_text(payload))
        return
    if output_format == "text" and workflow == "promotion":
        print(_render_promotion_text(payload))
        return
    if output_format == "text" and workflow == "template":
        print(_render_template_text(payload))
        return
    if output_format == "text" and workflow == "revalidation":
        print(_render_revalidation_text(payload))
        return
    if output_format == "text" and workflow == "revalidation_dir":
        print(_render_revalidation_dir_text(payload))
        return
    print(json.dumps(payload, ensure_ascii=False))



def _render_generation_text(payload: dict[str, Any]) -> str:
    lines = [
        f"Status: {payload['status']}",
        f"Message: {payload.get('message', '')}",
        f"Run ID: {payload.get('run_id', '')}",
        f"Source ID: {payload.get('source_id', '')}",
        f"Project: {payload.get('project', '')}",
        f"Bundle: {payload.get('bundle_dir', '')}",
        f"Agent plan: {payload.get('agent_plan_path') or 'not_applicable'}",
        f"Input mode: {payload.get('input_mode', '')}",
        f"Cases: {payload.get('test_case_count', 0)}",
        f"Scenario rendering: {payload.get('scenario_rendering', 'not_requested')}",
    ]
    artifact_paths = payload.get("artifact_paths") or {}
    if artifact_paths:
        lines.append("Artifacts:")
        if artifact_paths.get("bundle"):
            lines.append(f"  - bundle: {artifact_paths['bundle']}")
        if artifact_paths.get("agent_plan"):
            lines.append(f"  - agent_plan: {artifact_paths['agent_plan']}")
        if artifact_paths.get("normalized_plan"):
            lines.append(f"  - normalized_plan: {artifact_paths['normalized_plan']}")
        if artifact_paths.get("summary"):
            lines.append(f"  - summary: {artifact_paths['summary']}")
    diagnostics = payload.get("diagnostics") or []
    if diagnostics:
        lines.append("Diagnostics:")
        for diagnostic in diagnostics[:12]:
            lines.append(
                f"  - {diagnostic.get('severity', '').lower()}: {diagnostic.get('code', '')}: {diagnostic.get('message', '')}"
            )
    return "\n".join(lines).rstrip()



def _render_authoring_text(payload: dict[str, Any]) -> str:
    lines = [
        f"Status: {payload['status']}",
        f"Message: {payload.get('message', '')}",
    ]
    if payload.get("output_path"):
        lines.extend(
            [
                f"Bundle: {payload.get('bundle_dir', '')}",
                f"Output: {payload['output_path']}",
                f"Template version: {payload.get('template_version', '')}",
                f"Input mode: {payload.get('input_mode', '')}",
            ]
        )
    if payload.get("file_path"):
        lines.extend(
            [
                f"File: {payload['file_path']}",
                f"Input mode: {payload.get('input_mode', '')}",
                f"Case count: {payload.get('case_count', 0)}",
            ]
        )
    if payload.get("validation_status_after_sync"):
        lines.extend(
            [
                f"Case count: {payload.get('case_count', 0)}",
                f"Validation after sync: {payload.get('validation_status_after_sync')}",
            ]
        )
    stage_policy = payload.get("stage_policy") or {}
    if stage_policy:
        lines.extend(
            [
                "Stage policy:",
                f"  - mode: {stage_policy.get('mode', '')}",
                f"  - rule: {stage_policy.get('rule', '')}",
            ]
        )
        for stage in stage_policy.get("stages") or []:
            line = f"  - {stage.get('name', '')}: {stage.get('required_gate', '')}"
            if stage.get("requires_passed_stage"):
                line += f" after {stage.get('requires_passed_stage')}"
            lines.append(line)
    stage_results = payload.get("stage_results") or {}
    if stage_results:
        lines.append("Stages:")
        for stage_name in payload.get("stage_order") or stage_results.keys():
            stage_payload = stage_results.get(stage_name) or {}
            stage_line = f"  - {stage_name}: {stage_payload.get('status', '')}"
            if stage_name == "authoring_plan":
                stage_line += (
                    f" ({stage_payload.get('compiled_case_count', 0)}/"
                    f"{stage_payload.get('case_count', 0)} cases compile)"
                )
            lines.append(stage_line)
    handoff = payload.get("handoff") or {}
    if handoff:
        lines.extend(
            [
                "Handoff:",
                f"  - scope: {handoff.get('scope', '')}",
                f"  - scenario_drafts_rendered: {handoff.get('scenario_drafts_rendered', False)}",
                f"  - promoted_scenarios: {handoff.get('promoted_scenarios', False)}",
            ]
        )
        next_commands = handoff.get("next_commands") or []
        if next_commands:
            lines.append("Next commands:")
            for command in next_commands:
                lines.append(f"  - {command.get('label', '')}: {command.get('command', '')}")
    diagnostics = payload.get("diagnostics") or []
    if diagnostics:
        lines.append("Diagnostics:")
        for diagnostic in diagnostics:
            lines.append(f"  - {diagnostic.get('code', '')}: {diagnostic.get('message', '')}")
            details = diagnostic.get("details") or {}
            if details.get("rule"):
                lines.append(f"    Rule: {details.get('rule', '')}")
            if details.get("hint"):
                lines.append(f"    Hint: {details.get('hint', '')}")
            examples = details.get("supported_examples") or []
            if examples:
                lines.append("    Examples:")
                for example in examples[:6]:
                    lines.append(f"      - {example}")
            suggested_case = details.get("suggested_case") or {}
            if suggested_case.get("title"):
                lines.append(
                    f"    Suggest: {suggested_case.get('title', '')} [{suggested_case.get('http_method', '')} {suggested_case.get('endpoint_path', '')}]"
                )
            if suggested_case.get("objective"):
                lines.append(f"    Objective: {suggested_case.get('objective', '')}")
    template = payload.get("template") or {}
    if template:
        lines.append("Template preview:")
        for preview_line in json.dumps(template, ensure_ascii=False, indent=2).splitlines()[:12]:
            lines.append(f"  {preview_line}")
    return "\n".join(lines).rstrip()



def _render_review_text(payload: dict[str, Any]) -> str:
    lines = [
        f"Status: {payload['status']}",
        f"Run ID: {payload['run_id']}",
        f"Source ID: {payload['source_id']}",
        f"Drafts: {payload['draft_count']}",
        f"Partial drafts: {payload.get('partial_draft_count', 0)}",
        f"Strongly supported drafts: {payload.get('strongly_supported_draft_count', 0)}",
        f"Deferred items: {payload.get('deferred_item_count', 0)}",
        f"Drafts with edit targets: {payload.get('drafts_with_edit_targets', 0)}",
        f"Total edit targets: {payload.get('total_edit_targets', 0)}",
        f"Average completeness: {payload.get('average_completeness_ratio', 0.0)}",
        f"Close to runnable: {payload.get('close_to_runnable_count', 0)}",
        "",
    ]
    review_set = payload.get("review_set") or {}
    for item in review_set.get("items", []):
        lines.extend(
            [
                f"Draft: {item['draft_id']}",
                f"Title: {item.get('title', '')}",
                f"Status: {item['readiness_category']}",
                f"Parse: {item['parse_status']}",
                f"Route: {item.get('route_status', 'unknown')}",
                f"Promotion advisory: {item.get('promotion_advisory', '')}",
                "Checklist:",
            ]
        )
        checklist = item.get("checklist") or {}
        for line in checklist.get("diff_lines", []):
            lines.append(f"  {line}")
        lines.append("Remaining gaps:")
        gap_summary = item.get("gap_summary") or {}
        for code in gap_summary.get("gap_codes", []):
            lines.append(f"  - {code}")
        lines.append("Edit targets:")
        edit_targets = (item.get("edit_targets") or {}).get("targets", [])
        if edit_targets:
            for target in edit_targets:
                lines.append(
                    f"  - [{target['section_name']}] {target['target_type']}: {target['suggested_minimum_patch']}"
                )
                suggestion = target.get("patch_suggestion") or {}
                template_id = suggestion.get("template_id")
                if template_id:
                    lines.append(f"    Template: {template_id}")
                    preview = suggestion.get("template_preview") or []
                    if preview:
                        lines.append("    Preview:")
                        for preview_line in preview[:6]:
                            lines.append(f"      {preview_line}")
        else:
            lines.append("  - none")
        lines.append("")

    deferred_items = review_set.get("deferred_items") or []
    if deferred_items:
        lines.append("Deferred:")
        for item in deferred_items:
            lines.append(f"  {item['case_id']}: {item['reason_code']}")
        lines.append("")
    diagnostics = payload.get("diagnostics") or []
    if diagnostics:
        lines.append("Review diagnostics:")
        for diagnostic in diagnostics:
            lines.append(f"  - {diagnostic.get('code', '')}: {diagnostic.get('message', '')}")
            suggested_case = (diagnostic.get("details") or {}).get("suggested_case") or {}
            if suggested_case.get("title"):
                lines.append(
                    f"    Suggest: {suggested_case.get('title', '')} [{suggested_case.get('http_method', '')} {suggested_case.get('endpoint_path', '')}]"
                )
            if suggested_case.get("objective"):
                lines.append(f"    Objective: {suggested_case.get('objective', '')}")
    return "\n".join(lines).rstrip()



def _render_template_text(payload: dict[str, Any]) -> str:
    if "template" in payload:
        template = payload["template"]
        lines = [
            f"Status: {payload['status']}",
            f"Template: {template['template_id']}",
            f"Target type: {template['target_type']}",
            f"Section: {template['section_name']}",
            f"Title: {template['title']}",
            f"Description: {template['description']}",
            "Preview:",
        ]
        lines.extend(f"  {line}" for line in template.get("template_lines", []))
        usage_notes = template.get("usage_notes", [])
        if usage_notes:
            lines.append("Usage notes:")
            lines.extend(f"  - {line}" for line in usage_notes)
        return "\n".join(lines)

    lines = [
        f"Status: {payload['status']}",
        f"Catalog version: {payload.get('catalog_version', '')}",
        f"Templates: {payload.get('template_count', 0)}",
        "",
    ]
    for template in payload.get("templates", []):
        lines.append(
            f"- {template['template_id']} [{template['section_name']}] {template['target_type']}: {template['title']}"
        )
    return "\n".join(lines).rstrip()



def _render_promotion_text(payload: dict[str, Any]) -> str:
    lines = [
        f"Status: {payload['status']}",
        f"Run ID: {payload.get('run_id', '')}",
    ]
    if "draft_id" in payload:
        lines.extend(
            [
                f"Draft ID: {payload.get('draft_id', '')}",
                f"Source: {payload.get('source_path') or ''}",
                f"Target: {payload.get('target_path') or ''}",
            ]
        )
    else:
        lines.extend(
            [
                f"Requested: {payload.get('requested_count', 0)}",
                f"Promoted: {payload.get('promoted_count', 0)}",
                f"Errors: {payload.get('error_count', 0)}",
                f"Target dir: {payload.get('target_dir') or ''}",
            ]
        )
        results = payload.get("results") or []
        if results:
            lines.append("Results:")
            for item in results:
                lines.append(
                    f"  - {item.get('draft_id', '')}: {item.get('status', '')} -> {item.get('target_path') or ''}"
                )
    diagnostics = payload.get("diagnostics") or []
    if diagnostics:
        lines.append("Diagnostics:")
        for diagnostic in diagnostics:
            lines.append(f"  - {diagnostic.get('code', '')}: {diagnostic.get('message', '')}")
    if payload.get("promotion_result_path"):
        lines.append(f"Promotion result: {payload.get('promotion_result_path')}")
    return "\n".join(lines).rstrip()



def _render_revalidation_text(payload: dict[str, Any]) -> str:
    display_status = payload.get("readiness_category") or payload["status"]
    lines = [
        f"Status: {display_status}",
        f"File: {payload['file_path']}",
        f"Parse: {payload['parse_status']}",
        f"Validation mode: {payload.get('validation_mode', 'parser')}",
        f"Compile: {payload.get('compile_status') or 'not_requested'}",
        f"Preflight: {payload.get('preflight_status') or 'not_requested'}",
        f"Readiness: {payload.get('readiness_category', payload.get('execution_readiness_category', ''))}",
        f"Promotion advisory: {payload.get('promotion_advisory', '')}",
        f"Completeness: {payload.get('completeness_ratio', 0.0)}",
    ]
    if payload.get("based_on_generated_draft"):
        lines.extend(
            [
                "Origin: generated draft",
                f"Generation run: {payload.get('generation_run_id', '')}",
                f"Draft ID: {payload.get('draft_id', '')}",
            ]
        )
    lines.append("Checklist:")
    checklist = payload.get("checklist") or {}
    for line in checklist.get("diff_lines", []):
        lines.append(f"  {line}")
    lines.append("Remaining gaps:")
    gap_summary = payload.get("gap_summary") or {}
    gap_codes = gap_summary.get("gap_codes", [])
    if gap_codes:
        for code in gap_codes:
            lines.append(f"  - {code}")
    else:
        lines.append("  - none")
    compile_validation = payload.get("compile_validation") or {}
    compile_issues = compile_validation.get("issues") or []
    compile_warnings = compile_validation.get("warnings") or []
    if compile_issues or compile_warnings:
        lines.append("Compile issues:")
        for issue in compile_issues:
            lines.append(f"  - {issue.get('issue_type', '')}: {issue.get('message', '')}")
        for warning in compile_warnings:
            lines.append(f"  - warning/{warning.get('issue_type', '')}: {warning.get('message', '')}")
    preflight_validation = payload.get("preflight_validation") or {}
    preflight_issues = preflight_validation.get("issues") or []
    preflight_warnings = preflight_validation.get("warnings") or []
    if preflight_issues or preflight_warnings:
        lines.append("Preflight issues:")
        for issue in preflight_issues:
            lines.append(f"  - {issue.get('issue_type', '')}: {issue.get('message', '')}")
        for warning in preflight_warnings:
            lines.append(f"  - warning/{warning.get('issue_type', '')}: {warning.get('message', '')}")
    validation_notes = payload.get("validation_notes") or []
    if validation_notes:
        lines.append("Validation notes:")
        for note in validation_notes:
            lines.append(f"  - {note}")
    lines.append("Edit targets:")
    edit_targets = (payload.get("edit_targets") or {}).get("targets", [])
    if edit_targets:
        for target in edit_targets:
            lines.append(
                f"  - [{target['section_name']}] {target['target_type']}: {target['suggested_minimum_patch']}"
            )
            suggestion = target.get("patch_suggestion") or {}
            if suggestion.get("template_id"):
                lines.append(f"    Template: {suggestion['template_id']}")
    else:
        lines.append("  - none")
    diagnostics = payload.get("diagnostics") or []
    if diagnostics:
        lines.append("Parser diagnostics:")
        for diagnostic in diagnostics:
            lines.append(f"  - {diagnostic.get('severity', '')}: {diagnostic.get('message', '')}")
    return "\n".join(lines).rstrip()



def _render_revalidation_dir_text(payload: dict[str, Any]) -> str:
    lines = [
        f"Status: {payload['status']}",
        f"Directory: {payload['directory_path']}",
        f"Validation mode: {payload.get('validation_mode', 'parser')}",
        f"Scenarios: {payload.get('scenario_count', 0)}",
        f"Failures: {payload.get('failure_count', 0)}",
    ]
    readiness_counts = payload.get("readiness_counts") or {}
    if readiness_counts:
        lines.append("Readiness counts:")
        for key, value in sorted(readiness_counts.items()):
            lines.append(f"  - {key}: {value}")
    failure_items = payload.get("failure_items") or []
    if failure_items:
        lines.append("Failures:")
        for item in failure_items:
            lines.append(
                f"  - {item.get('file_path', '')}: parse={item.get('parse_status', '')} readiness={item.get('readiness_category', '')}"
            )
            gap_codes = item.get("gap_codes") or []
            if gap_codes:
                lines.append(f"    Gaps: {', '.join(str(code) for code in gap_codes)}")
    validation_notes = payload.get("validation_notes") or []
    if validation_notes:
        lines.append("Validation notes:")
        for note in validation_notes:
            lines.append(f"  - {note}")
    return "\n".join(lines).rstrip()

