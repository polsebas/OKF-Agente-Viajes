from datetime import datetime, timezone
from unittest.mock import patch

import frontmatter
from git import Repo

from core.maintenance_cron import run_nightly_maintenance
from core.maintenance_report import MAINTENANCE_REPORT_CONCEPT_ID
from core.validation_engine import build_default_engine
from tools.okf_adapter import _known_tags_from_bundle, parse_bundle


def _report_path(vault_root) -> str:
    return str(vault_root / "_meta" / "maintenance-report.md")


def test_run_nightly_maintenance_writes_validated_report_and_commits(temp_vault):
    sunday = datetime(2026, 7, 12, 3, 0, tzinfo=timezone.utc)  # domingo

    with patch("core.maintenance_cron.datetime") as mock_dt:
        mock_dt.now.return_value = sunday
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        run_nightly_maintenance(str(temp_vault))

    report_file = temp_vault / "_meta" / "maintenance-report.md"
    assert report_file.exists()

    post = frontmatter.load(report_file)
    assert post.metadata["type"] == "maintenance-report"
    assert "timestamp" in post.metadata
    assert "## Integrity scan" in post.content
    assert "Status: PASS" in post.content
    assert "## Action needed" in post.content

    bundle = parse_bundle(str(temp_vault))
    concept = bundle[MAINTENANCE_REPORT_CONCEPT_ID]
    engine = build_default_engine(known_tags=_known_tags_from_bundle(bundle))
    result = engine.validate_concept(concept, bundle)
    assert result.passed is True

    repo = Repo(temp_vault)
    messages = [commit.message.strip() for commit in repo.iter_commits(max_count=5)]
    assert any("maintenance: write maintenance report" in message for message in messages)


def test_run_nightly_maintenance_zero_pending_shows_exact_all_clear_message(temp_vault):
    monday = datetime(2026, 7, 13, 3, 0, tzinfo=timezone.utc)  # lunes: sin canonicalizacion

    with patch("core.maintenance_cron.datetime") as mock_dt:
        mock_dt.now.return_value = monday
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        run_nightly_maintenance(str(temp_vault))

    content = (temp_vault / "_meta" / "maintenance-report.md").read_text(encoding="utf-8")
    assert "Nothing needs your attention." in content
    assert "0 plans still awaiting your approval" in content
