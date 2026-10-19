"""构建“现代楷书参考 → 早期书体”的成对训练清单，不联网、不训练。"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hanzi_evolution.db import open_db
from hanzi_evolution.ml.pairs import CORE_TARGETS, write_pair_dataset
from hanzi_evolution.store import export_rows


def main():
    parser = argparse.ArgumentParser(description="楷书参考到早期书体的成对数据清单")
    parser.add_argument("--output", type=Path, default=ROOT / "data/ml/style_pairs")
    parser.add_argument("--db", type=Path, default=ROOT / "data/hanzi.sqlite")
    parser.add_argument("--styles", default=",".join(CORE_TARGETS),
                        help="逗号分隔的目标书体，默认四种核心书体")
    parser.add_argument("--all-styles", action="store_true",
                        help="除现代楷书参考外的全部书体")
    parser.add_argument("--seed", type=int, default=20261019)
    args = parser.parse_args()

    rows = export_rows(open_db(args.db), include_quarantine=True, include_test=False)
    if args.all_styles:
        styles = tuple(sorted({row["script_style"] for row in rows
                               if row.get("script_style")
                               and row["script_style"] != "kaishu_reference"}))
    else:
        styles = tuple(style.strip() for style in args.styles.split(",") if style.strip())
    stats = write_pair_dataset(rows, args.output, target_styles=styles, seed=args.seed)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
