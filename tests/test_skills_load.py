"""Skills de runtime: LocalSkills carga ambas carpetas sin error."""

from pathlib import Path

import frontmatter
from agno.skills import LocalSkills, Skills

_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


def test_skills_load_both_folders_without_error():
    skills = Skills(loaders=[LocalSkills(str(_SKILLS_DIR))])
    loaded = {skill.name: skill for skill in skills.get_all_skills()}

    assert "okf-conformance-consult" in loaded
    assert "tag-taxonomy-conventions" in loaded


def test_skill_md_files_have_valid_frontmatter():
    for folder in ("okf-conformance-consult", "tag-taxonomy-conventions"):
        skill_path = _SKILLS_DIR / folder / "SKILL.md"
        post = frontmatter.load(skill_path)
        assert post.get("name"), f"{folder}/SKILL.md falta 'name' en el frontmatter"
        assert post.get("description"), f"{folder}/SKILL.md falta 'description' en el frontmatter"
