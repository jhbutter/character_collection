"""兼容入口：实现位于 hanzi_evolution.collection.batch。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hanzi_evolution.collection.batch import main

if __name__ == "__main__":
    raise SystemExit(main())
