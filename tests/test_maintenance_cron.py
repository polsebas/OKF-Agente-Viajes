from git import Repo

from core.maintenance_cron import apply_approved_plans, run_integrity_scan, run_tag_canonicalization
from tools.okf_adapter import parse_bundle


def test_run_integrity_scan_passes_on_healthy_fixture(temp_vault):
    result = run_integrity_scan(str(temp_vault))
    assert result.passed is True


def test_run_tag_canonicalization_finds_jp_to_japon_candidate(temp_vault):
    plans = run_tag_canonicalization(str(temp_vault), use_judge=False)

    assert len(plans) == 1
    plan = plans[0]
    assert plan.status == "pending"
    jp_candidates = [c for c in plan.candidates if "jp" in c.tags_to_merge]
    assert len(jp_candidates) == 1
    assert jp_candidates[0].proposed_canonical == "japon"
    assert "dias/dia-02-tokio" in jp_candidates[0].affected_concept_ids

    plan_path = temp_vault / ".okf_meta" / "pending_merges" / f"{plan.plan_id}.json"
    assert plan_path.exists()


def test_run_tag_canonicalization_does_not_touch_vault(temp_vault):
    before = parse_bundle(str(temp_vault))
    run_tag_canonicalization(str(temp_vault), use_judge=False)
    after = parse_bundle(str(temp_vault))

    assert before["dias/dia-02-tokio"].tags == after["dias/dia-02-tokio"].tags == ["jp", "tokio"]


def test_apply_approved_plans_rewrites_tags_and_commits(temp_vault):
    from core.approve_plan import approve_plan

    plans = run_tag_canonicalization(str(temp_vault), use_judge=False)
    plan = plans[0]
    approve_plan(plan.plan_id, plans_dir=str(temp_vault / ".okf_meta" / "pending_merges"))

    acted_on = apply_approved_plans(str(temp_vault))
    assert len(acted_on) == 1
    assert acted_on[0].status == "applied"

    after = parse_bundle(str(temp_vault))
    assert "jp" not in after["dias/dia-02-tokio"].tags
    assert "japon" in after["dias/dia-02-tokio"].tags

    repo = Repo(temp_vault)
    last_commit = next(repo.iter_commits(max_count=1))
    assert "apply_tag_rewrite" in last_commit.message
