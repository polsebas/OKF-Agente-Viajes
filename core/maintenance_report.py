"""Serializacion determinista del reporte de mantenimiento como concept OKF."""

from __future__ import annotations

from datetime import datetime, timezone

from core.validation_engine import build_default_engine
from schemas.okf_concept import OKFConcept
from schemas.tag_taxonomy import TagMergePlan
from schemas.validation import ValidationResult, ValidationSeverity
from tools.okf_adapter import _git_commit, _known_tags_from_bundle, _write_concept_file, parse_bundle

MAINTENANCE_REPORT_CONCEPT_ID = "_meta/maintenance-report"


def _pluralize(count: int, singular: str, plural: str) -> str:
    return singular if count == 1 else plural


def _format_integrity_section(result: ValidationResult) -> str:
    if result.passed:
        return "## Integrity scan\nStatus: PASS"
    errors = [issue for issue in result.issues if issue.severity == ValidationSeverity.ERROR]
    issue_parts = [
        f"[{issue.concept_id} {issue.rule_name} {issue.message}]" for issue in errors
    ]
    issues_text = ", ".join(issue_parts)
    return (
        f"## Integrity scan\n"
        f"Status: FAIL — {len(errors)} issues found: {issues_text}"
    )


def _format_canonicalization_section(
    new_candidates: list[TagMergePlan],
    applied_plans: list[TagMergePlan],
    pending_count: int,
) -> str:
    lines = ["## Tag canonicalization"]

    new_count = len(new_candidates)
    if new_count == 0:
        lines.append("0 new merge candidates proposed this run")
    else:
        plan_ids = ", ".join(plan.plan_id for plan in new_candidates)
        noun = _pluralize(new_count, "new merge candidate proposed", "new merge candidates proposed")
        lines.append(f"{new_count} {noun} this run: {plan_ids}")

    applied_count = len(applied_plans)
    if applied_count == 0:
        lines.append("0 plans applied since last report")
    else:
        plan_ids = ", ".join(plan.plan_id for plan in applied_plans)
        noun = _pluralize(applied_count, "plan applied", "plans applied")
        lines.append(f"{applied_count} {noun} since last report: {plan_ids}")

    if pending_count == 0:
        lines.append("0 plans still awaiting your approval")
    else:
        noun = _pluralize(pending_count, "plan still awaiting", "plans still awaiting")
        lines.append(
            f"{pending_count} {noun} your approval — run `python -m core.approve_plan --list`"
        )

    return "\n".join(lines)


def _format_action_needed(
    integrity_result: ValidationResult,
    pending_count: int,
) -> str:
    if pending_count > 0:
        noun = _pluralize(pending_count, "plan", "plans")
        return f"You have {pending_count} pending tag merge {noun}. Nothing else needs attention."
    if integrity_result.passed:
        return "Nothing needs your attention."
    return "Integrity scan failed — review issues above."


def _build_report_body(
    integrity_result: ValidationResult,
    new_candidates: list[TagMergePlan],
    applied_plans: list[TagMergePlan],
    pending_count: int,
) -> str:
    sections = [
        _format_integrity_section(integrity_result),
        _format_canonicalization_section(new_candidates, applied_plans, pending_count),
        f"## Action needed\n{_format_action_needed(integrity_result, pending_count)}",
    ]
    return "\n\n".join(sections) + "\n"


def write_maintenance_report(
    integrity_result: ValidationResult,
    new_candidates: list[TagMergePlan],
    applied_plans: list[TagMergePlan],
    pending_count: int,
    bundle_root: str,
) -> None:
    """
    Deterministic serialization. Overwrites _meta/maintenance-report.md as an
    OKF concept (type: maintenance-report) — same file every run, git log is
    the history, we don't need N report files piling up.
    Goes through the same validate_concept() gate as any other write, then
    commits to git. If validation somehow fails on our own generated report,
    that's a bug to surface loudly, not swallow.
    """
    timestamp = datetime.now(timezone.utc).replace(microsecond=0)
    body = _build_report_body(integrity_result, new_candidates, applied_plans, pending_count)

    bundle = parse_bundle(bundle_root)
    concept = OKFConcept(
        concept_id=MAINTENANCE_REPORT_CONCEPT_ID,
        type="maintenance-report",
        timestamp=timestamp,
        body=body,
        links=[],
        tags=[],
    )

    engine = build_default_engine(known_tags=_known_tags_from_bundle(bundle))
    result = engine.validate_concept(concept, bundle)
    if not result.passed:
        error_lines = [
            f"[{issue.severity.value}] {issue.rule_name} en '{issue.concept_id}': {issue.message}"
            for issue in result.issues
            if issue.severity == ValidationSeverity.ERROR
        ]
        raise RuntimeError(
            "Bug: el reporte de mantenimiento generado no paso validate_concept():\n"
            + "\n".join(error_lines)
        )

    _write_concept_file(bundle_root, concept)
    _git_commit(bundle_root, "maintenance: write maintenance report")
