"""Safe compatibility entry point. Dry run unless the exact target is confirmed."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cleanup import main

if __name__ == "__main__":
    raise SystemExit(main())
