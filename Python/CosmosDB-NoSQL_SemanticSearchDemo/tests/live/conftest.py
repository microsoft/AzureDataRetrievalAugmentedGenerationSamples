import json
from pathlib import Path

import pytest

from search_demo import Settings, get_containers
from container_setup import validate_policy

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures/movies.synthetic.json"


@pytest.fixture
def fixture_rows():
    if not FIXTURE_PATH.is_file():
        pytest.fail("Generate fixtures first: python scripts/make-fixtures.py")
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def live_containers():
    containers = get_containers(Settings.from_env())
    for name, container in containers.items():
        validate_policy(container.read(), name)
    return containers


@pytest.fixture
def loaded_containers(live_containers, fixture_rows):
    for container in live_containers.values():
        for item in fixture_rows:
            actual = container.read_item(item=item["id"], partition_key=item["id"])
            assert all(actual[key] == item[key] for key in item), (
                "Fixture missing or changed. Run the documented confirmed loader first.")
    return live_containers
