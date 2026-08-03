from datetime import datetime, timezone

from core.maintenance_cron import apply_approved_plans
from schemas.tag_taxonomy import TagMergeCandidate, TagMergePlan
from tools.okf_adapter import parse_bundle


def _jp_candidate() -> TagMergeCandidate:
    return TagMergeCandidate(
        proposed_canonical="japon",
        tags_to_merge=["jp"],
        similarity_score=1.0,
        affected_concept_ids=["dias/dia-02-tokio"],
        rationale="'jp' ya es un alias conocido de 'japon' en la taxonomia.",
    )


def _write_plan(vault_root, plan: TagMergePlan) -> None:
    plans_dir = vault_root / ".okf_meta" / "pending_merges"
    plans_dir.mkdir(parents=True, exist_ok=True)
    (plans_dir / f"{plan.plan_id}.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")


def test_apply_approved_plans_only_touches_approved_plan(temp_vault):
    now = datetime.now(timezone.utc).isoformat()
    pending_plan = TagMergePlan(
        plan_id="pending-only",
        created_at=now,
        candidates=[_jp_candidate()],
        status="pending",
    )
    approved_plan = TagMergePlan(
        plan_id="approved-to-apply",
        created_at=now,
        candidates=[_jp_candidate()],
        status="approved",
    )
    pending_path = temp_vault / ".okf_meta" / "pending_merges" / "pending-only.json"
    approved_path = temp_vault / ".okf_meta" / "pending_merges" / "approved-to-apply.json"

    _write_plan(temp_vault, pending_plan)
    _write_plan(temp_vault, approved_plan)
    pending_before = pending_path.read_text(encoding="utf-8")

    acted_on = apply_approved_plans(str(temp_vault))

    assert [plan.plan_id for plan in acted_on] == ["approved-to-apply"]

    applied = TagMergePlan.model_validate_json(approved_path.read_text(encoding="utf-8"))
    assert applied.status == "applied"

    assert pending_path.read_text(encoding="utf-8") == pending_before
    untouched = TagMergePlan.model_validate_json(pending_path.read_text(encoding="utf-8"))
    assert untouched.status == "pending"

    after = parse_bundle(str(temp_vault))
    assert "jp" not in after["dias/dia-02-tokio"].tags
    assert "japon" in after["dias/dia-02-tokio"].tags
