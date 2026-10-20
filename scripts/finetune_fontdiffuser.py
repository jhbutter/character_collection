"""FontDiffuser 预训练权重实验兼容入口；实现位于 ml/fontdiffuser_adapter.py。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hanzi_evolution.ml.fontdiffuser_adapter import main


if __name__ == "__main__":
    main()
