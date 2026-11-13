import importlib.util
import json
from pathlib import Path

from load_data import prepare_items

ROOT = Path(__file__).resolve().parents[2]


def test_bundled_fixture_is_deterministic_valid_and_original():
    spec = importlib.util.spec_from_file_location("make_fixtures", ROOT / "scripts/make-fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    first, second = module.fixtures(), module.fixtures()
    assert first == second
    assert len(first) == 3
    assert len({row["id"] for row in first}) == 3
    assert all(row["id"].startswith("synthetic-") for row in first)
    assert prepare_items(first) == first
    for axis, row in enumerate(first):
        assert row["embedding"][axis] == 1.0
        assert sum(row["embedding"]) == 1.0


def test_materialized_fixture_matches_generator_if_present():
    path = ROOT / "tests/fixtures/movies.synthetic.json"
    # The normal setup command materializes the distributable preembedded JSON.
    if not path.exists():
        return
    spec = importlib.util.spec_from_file_location("make_fixtures", ROOT / "scripts/make-fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert json.loads(path.read_text(encoding="utf-8")) == module.fixtures()
