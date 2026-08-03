"""
CLI for reviewing and approving/rejecting pending tag merge plans.
Human-operated only. Never imported by agents/travel_agent.py or by any
Agno tool. This is the explicit approval step of our Two-Phase Commit
pattern for tag merges.

Usage:
    python -m core.approve_plan --list
    python -m core.approve_plan --approve <plan_id>
    python -m core.approve_plan --reject <plan_id>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.config import get_vault_root
from schemas.tag_taxonomy import TagMergePlan

DEFAULT_PLANS_DIR = ".okf_meta/pending_merges"


def _resolve_plans_dir(plans_dir: str) -> Path:
    path = Path(plans_dir)
    if path.is_absolute():
        return path
    return Path(get_vault_root()) / plans_dir


def _load_plan(plan_id: str, plans_dir: Path) -> TagMergePlan:
    plan_path = plans_dir / f"{plan_id}.json"
    if not plan_path.exists():
        raise FileNotFoundError(f"No existe ningun plan con plan_id '{plan_id}' en {plans_dir}.")
    return TagMergePlan.model_validate_json(plan_path.read_text(encoding="utf-8"))


def _save_plan(plan: TagMergePlan, plans_dir: Path) -> None:
    plans_dir.mkdir(parents=True, exist_ok=True)
    (plans_dir / f"{plan.plan_id}.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")


def list_pending_plans(plans_dir: str = DEFAULT_PLANS_DIR) -> list[TagMergePlan]:
    """Return all plans with status == 'pending', for human review."""
    resolved = _resolve_plans_dir(plans_dir)
    if not resolved.exists():
        return []
    pending = []
    for plan_path in sorted(resolved.glob("*.json")):
        plan = TagMergePlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
        if plan.status == "pending":
            pending.append(plan)
    return pending


def approve_plan(plan_id: str, plans_dir: str = DEFAULT_PLANS_DIR) -> TagMergePlan:
    """Set status -> 'approved'. Raise if plan_id not found or not 'pending'."""
    resolved = _resolve_plans_dir(plans_dir)
    plan = _load_plan(plan_id, resolved)
    if plan.status != "pending":
        raise ValueError(
            f"El plan '{plan_id}' tiene status '{plan.status}'; solo se pueden aprobar planes 'pending'."
        )
    updated = plan.model_copy(update={"status": "approved"})
    _save_plan(updated, resolved)
    return updated


def reject_plan(plan_id: str, plans_dir: str = DEFAULT_PLANS_DIR) -> TagMergePlan:
    """Set status -> 'rejected'. Rejected plans are kept, not deleted — audit trail."""
    resolved = _resolve_plans_dir(plans_dir)
    plan = _load_plan(plan_id, resolved)
    if plan.status != "pending":
        raise ValueError(
            f"El plan '{plan_id}' tiene status '{plan.status}'; solo se pueden rechazar planes 'pending'."
        )
    updated = plan.model_copy(update={"status": "rejected"})
    _save_plan(updated, resolved)
    return updated


def _print_pending(plans: list[TagMergePlan]) -> None:
    if not plans:
        print("No hay planes pendientes de aprobacion.")
        return
    for plan in plans:
        candidate_summary = ", ".join(
            f"{c.tags_to_merge} -> {c.proposed_canonical}" for c in plan.candidates
        )
        print(f"{plan.plan_id}  ({plan.created_at})  {candidate_summary or '(sin candidatos)'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Revisar y aprobar/rechazar planes de merge de tags.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="Listar planes con status pending.")
    group.add_argument("--approve", metavar="PLAN_ID", help="Aprobar un plan pendiente.")
    group.add_argument("--reject", metavar="PLAN_ID", help="Rechazar un plan pendiente.")
    parser.add_argument(
        "--plans-dir",
        default=DEFAULT_PLANS_DIR,
        help=f"Directorio de planes (default: {DEFAULT_PLANS_DIR} relativo al vault).",
    )
    args = parser.parse_args(argv)

    try:
        if args.list:
            _print_pending(list_pending_plans(args.plans_dir))
            return 0
        if args.approve:
            plan = approve_plan(args.approve, plans_dir=args.plans_dir)
            print(f"Aprobado: {plan.plan_id}")
            return 0
        if args.reject:
            plan = reject_plan(args.reject, plans_dir=args.plans_dir)
            print(f"Rechazado: {plan.plan_id}")
            return 0
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
