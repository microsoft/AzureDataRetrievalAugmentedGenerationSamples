"""Materialize the bundled original, preembedded integration fixture. No network."""

import argparse
import json
from pathlib import Path

MOVIES = [
    ("synthetic-orbit-rescue", "The Quiet Orbit",
     "An orbital rescue crew repairs a stranded spacecraft and brings its astronauts home.", 0),
    ("synthetic-garden", "The Patient Garden",
     "Neighbors restore a neglected city garden and share vegetables at a summer festival.", 1),
    ("synthetic-lighthouse", "Light Before Dawn",
     "A lighthouse keeper guides a fishing boat through a storm while repairing the harbor radio.", 2),
]


def fixtures():
    result = []
    for identifier, title, text, axis in MOVIES:
        vector = [0.0] * 1536
        vector[axis] = 1.0
        result.append({"id": identifier, "title": title, "text": text, "embedding": vector})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1]
                        / "tests/fixtures/movies.synthetic.json")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(fixtures(), indent=2) + "\n", encoding="utf-8")
    print("Wrote 3 original synthetic documents with 1536-dimensional deterministic vectors.")


if __name__ == "__main__":
    main()
