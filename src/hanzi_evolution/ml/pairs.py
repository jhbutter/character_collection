"""从字形数据库构建“现代楷书参考 → 早期书体”的成对清单。

任务边界：
- 源图固定为 kaishu_reference（现代楷书字头参考）；
- 目标为 jiaguwen / jinwen / xiaozhuan / lishu 等历史书体；
- 这是字体/书体风格转换，不是历史年代推演；
- 按汉字划分 train/val/test，禁止随机按图片划分造成同字泄漏。
"""

import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

SOURCE_STYLE = "kaishu_reference"
CORE_TARGETS = ("jiaguwen", "jinwen", "xiaozhuan", "lishu")


def split_characters(characters, seed=20261019, train=35, val=7):
    """按汉字划分，保证同一个字的所有配对只出现在一个 split。"""
    ordered = sorted(set(characters))
    random.Random(seed).shuffle(ordered)
    train_count = min(train, len(ordered))
    val_count = min(val, max(0, len(ordered) - train_count))
    result = {}
    for index, character in enumerate(ordered):
        if index < train_count:
            result[character] = "train"
        elif index < train_count + val_count:
            result[character] = "val"
        else:
            result[character] = "test"
    return result


def _pair_id(character, style, source_sha, target_sha):
    identity = f"{character}|{style}|{source_sha}|{target_sha}".encode()
    return hashlib.sha256(identity).hexdigest()[:24]


def build_pairs(rows, target_styles=CORE_TARGETS, seed=20261019):
    """rows 为 export_rows() 的扁平行；同一来源图片按 SHA-256 去重。"""
    target_styles = tuple(target_styles)
    sources = {}
    targets = defaultdict(lambda: defaultdict(dict))
    for row in rows:
        character = row.get("character")
        style = row.get("script_style")
        sha = row.get("sha256")
        if not character or not style or not sha or not row.get("image_path"):
            continue
        if style == SOURCE_STYLE:
            current = sources.get(character)
            if current is None or (row.get("glyph_id", 0), sha) < (
                    current.get("glyph_id", 0), current.get("sha256", "")):
                sources[character] = row
        elif style in target_styles:
            targets[character][style].setdefault(sha, row)

    characters = sorted(set(sources) & set(targets))
    split = split_characters(characters, seed=seed)
    pairs = []
    for character in characters:
        source = sources[character]
        for style in target_styles:
            for target_sha in sorted(targets[character].get(style, {})):
                target = targets[character][style][target_sha]
                pairs.append({
                    "pair_id": _pair_id(character, style, source["sha256"], target_sha),
                    "character": character,
                    "split": split[character],
                    "source_style": SOURCE_STYLE,
                    "target_style": style,
                    "source_image": source["image_path"],
                    "target_image": target["image_path"],
                    "source_sha256": source["sha256"],
                    "target_sha256": target_sha,
                    "source_glyph_id": source.get("glyph_id"),
                    "target_glyph_id": target.get("glyph_id"),
                    "source_source_id": source.get("source_id"),
                    "target_source_id": target.get("source_id"),
                    "source_record_id": source.get("source_record_id"),
                    "target_record_id": target.get("source_record_id"),
                    "source_url": source.get("source_url"),
                    "target_url": target.get("original_url"),
                    "mapping_status": target.get("mapping_status"),
                    "review_status": target.get("review_status"),
                })
    return pairs


def summarize(pairs):
    by_style = Counter(pair["target_style"] for pair in pairs)
    by_split = Counter(pair["split"] for pair in pairs)
    by_style_split = Counter((pair["target_style"], pair["split"]) for pair in pairs)
    style_characters = defaultdict(set)
    split_characters = defaultdict(set)
    for pair in pairs:
        style_characters[pair["target_style"]].add(pair["character"])
        split_characters[pair["split"]].add(pair["character"])
    styles = sorted(by_style)
    common = set.intersection(*(style_characters[style] for style in styles)) if styles else set()
    return {
        "characters": len({pair["character"] for pair in pairs}),
        "pairs": len(pairs),
        "unique_source_images": len({pair["source_sha256"] for pair in pairs}),
        "unique_target_images": len({pair["target_sha256"] for pair in pairs}),
        "target_styles": styles,
        "characters_by_style": {style: len(style_characters[style]) for style in styles},
        "characters_by_split": {split: len(split_characters[split])
                                for split in sorted(split_characters)},
        "characters_all_target_styles": len(common),
        "by_style": dict(sorted(by_style.items())),
        "by_split": dict(sorted(by_split.items())),
        "by_style_split": {f"{style}/{split}": count
                           for (style, split), count in sorted(by_style_split.items())},
    }


def write_pair_dataset(rows, output, target_styles=CORE_TARGETS, seed=20261019):
    pairs = build_pairs(rows, target_styles=target_styles, seed=seed)
    if not pairs:
        raise ValueError("没有可用的楷书参考与目标书体配对")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    pairs.sort(key=lambda pair: (pair["character"], pair["target_style"],
                                 pair["target_sha256"]))
    with (output / "manifest.jsonl").open("w", encoding="utf-8") as handle:
        for pair in pairs:
            handle.write(json.dumps(pair, ensure_ascii=False, sort_keys=True) + "\n")
    stats = summarize(pairs)
    stats["seed"] = seed
    stats["source_style"] = SOURCE_STYLE
    stats["target_styles"] = list(target_styles)
    (output / "stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    return stats
