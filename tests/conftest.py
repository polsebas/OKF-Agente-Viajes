import shutil
from pathlib import Path

import pytest

FIXTURE_VAULT = Path(__file__).resolve().parent.parent / "fixtures" / "sample_vault"


@pytest.fixture
def sample_vault_path() -> Path:
    return FIXTURE_VAULT


@pytest.fixture
def temp_vault(tmp_path, monkeypatch):
    """Copia el fixture a un directorio temporal con su propio repo git y
    apunta OKF_VAULT_ROOT ahi, para que ningun test escriba sobre
    fixtures/sample_vault ni sobre un repo git real del proyecto."""
    dest = tmp_path / "vault"
    shutil.copytree(FIXTURE_VAULT, dest)

    from git import Repo

    repo = Repo.init(dest)
    repo.git.add(A=True)
    repo.index.commit("fixture inicial")

    monkeypatch.setenv("OKF_VAULT_ROOT", str(dest))

    from tools import okf_adapter

    okf_adapter.invalidate_bundle_cache()
    yield dest
    okf_adapter.invalidate_bundle_cache()
