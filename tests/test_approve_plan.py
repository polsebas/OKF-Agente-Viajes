from datetime import datetime, timezone

import pytest

from core.approve_plan import approve_plan, list_pending_plans, reject_plan
from schemas.tag_taxonomy import TagMergeCandidate, TagMergePlan


def _write_plan(vault_root, plan: TagMergePlan) -> None:
    plans_dir = vault_root / ".okf_meta" / "pending_merges"
    plans_dir.mkdir(parents=True, exist_ok=True)
    (plans_dir / f"{plan.plan_id}.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")


def _sample_candidate() -> TagMergeCandidate:
    return TagMergeCandidate(
        proposed_canonical="japon",
        tags_to_merge=["jp"],
        similarity_score=1.0,
        affected_concept_ids=["dias/dia-02-tokio"],
        rationale="Alias conocido.",
    )


def test_approve_plan_sets_status_to_approved(temp_vault):
    plan = TagMergePlan(
        plan_id="pending-plan-001",
        created_at=datetime.now(timezone.utc).isoformat(),
        candidates=[_sample_candidate()],
        status="pending",
    )
    _write_plan(temp_vault, plan)

    approved = approve_plan("pending-plan-001", plans_dir=str(temp_vault / ".okf_meta" / "pending_merges"))

    assert approved.status == "approved"
    assert approved.plan_id == "pending-plan-001"


def test_reject_plan_sets_status_and_keeps_file(temp_vault):
    plan = TagMergePlan(
        plan_id="pending-plan-002",
        created_at=datetime.now(timezone.utc).isoformat(),
        candidates=[_sample_candidate()],
        status="pending",
    )
    _write_plan(temp_vault, plan)
    plan_path = temp_vault / ".okf_meta" / "pending_merges" / "pending-plan-002.json"

    rejected = reject_plan("pending-plan-002", plans_dir=str(temp_vault / ".okf_meta" / "pending_merges"))

    assert rejected.status == "rejected"
    assert plan_path.exists()
    persisted = TagMergePlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    assert persisted.status == "rejected"


def test_list_pending_plans_returns_only_pending(temp_vault):
    _write_plan(
        temp_vault,
        TagMergePlan(
            plan_id="pending-a",
            created_at=datetime.now(timezone.utc).isoformat(),
            candidates=[_sample_candidate()],
            status="pending",
        ),
    )
    _write_plan(
        temp_vault,
        TagMergePlan(
            plan_id="approved-b",
            created_at=datetime.now(timezone.utc).isoformat(),
            candidates=[_sample_candidate()],
            status="approved",
        ),
    )

    pending = list_pending_plans(plans_dir=str(temp_vault / ".okf_meta" / "pending_merges"))

    assert [plan.plan_id for plan in pending] == ["pending-a"]


def test_approve_plan_raises_if_not_pending(temp_vault):
    _write_plan(
        temp_vault,
        TagMergePlan(
            plan_id="already-approved",
            created_at=datetime.now(timezone.utc).isoformat(),
            candidates=[_sample_candidate()],
            status="approved",
        ),
    )

    with pytest.raises(ValueError, match="solo se pueden aprobar planes 'pending'"):
        approve_plan("already-approved", plans_dir=str(temp_vault / ".okf_meta" / "pending_merges"))
