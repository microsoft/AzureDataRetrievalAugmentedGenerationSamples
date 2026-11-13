import json
import os
from pathlib import Path

import pytest

from load_data import main

pytestmark = pytest.mark.live
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/movies.synthetic.json"


def test_repeatable_confirmed_loader_and_readbacks(live_containers, fixture_rows, capsys):
    if os.getenv("ALLOW_FIXTURE_UPSERT") != "1":
        pytest.fail("Live writes require ALLOW_FIXTURE_UPSERT=1; only stable fixture IDs are upserted.")
    args = ["--path_to_json_array", str(FIXTURE), "--text_field_name", "text",
            "--vector_field_name", "embedding", "--re_embed", "False",
            "--existing-only", "--max-items", "3", "--confirm-write", "--concurrency", "1"]
    for _ in range(2):
        assert main(args) == 0, "Loader failed; inspect sanitized CLI output."
        output = json.loads(capsys.readouterr().out)
        assert output["selected_items"] == 3
        for counts in output["containers"].values():
            assert counts == {"attempted": 3, "succeeded": 3, "failed": 0}
        for container in live_containers.values():
            for row in fixture_rows:
                actual = container.read_item(item=row["id"], partition_key=row["id"])
                assert all(actual[key] == row[key] for key in row)
            values = list(container.query_items(
                "SELECT VALUE COUNT(1) FROM c WHERE c.id IN (@a, @b, @c)",
                parameters=[{"name": name, "value": row["id"]}
                            for name, row in zip(("@a", "@b", "@c"), fixture_rows)],
                enable_cross_partition_query=True))
            assert values == [3], "Stable IDs must not create duplicate fixtures."
