import json
from pathlib import Path

import pytest


@pytest.fixture
def temp_state_path(tmp_path: Path) -> Path:
    return tmp_path / "state.json"


@pytest.fixture
def temp_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "wiki" / "sources").mkdir(parents=True)
    (vault / "wiki" / "entities").mkdir(parents=True)
    (vault / "wiki" / "concepts").mkdir(parents=True)
    (vault / "wiki" / "analyses").mkdir(parents=True)
    (vault / "raw" / "youtube").mkdir(parents=True)
    (vault / "index.md").write_text(
        "# Index\n\n## Entities\n\n## Concepts\n\n## Sources\n\n## Analyses\n"
    )
    (vault / "log.md").write_text("# Log\n")
    return vault


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


def load_fixture_json(fixtures_dir: Path, name: str):
    return json.loads((fixtures_dir / name).read_text())
