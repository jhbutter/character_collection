import json

import pytest

from hanzi_evolution.ml.pairs import build_pairs, split_characters, write_pair_dataset


def row(character, style, sha, glyph_id, path=None):
    return {
        "character": character,
        "script_style": style,
        "sha256": sha,
        "image_path": path or f"images/original/{sha[:2]}/{sha}.png",
        "glyph_id": glyph_id,
        "source_id": f"source-{style}",
        "source_record_id": f"{character}-{style}",
        "source_url": f"https://example.invalid/{character}",
        "original_url": f"https://example.invalid/{character}/{style}",
        "mapping_status": "unverified",
        "review_status": "pending",
    }


def rows():
    return [
        row("一", "kaishu_reference", "a" * 64, 1),
        row("天", "kaishu_reference", "b" * 64, 2),
        row("一", "lishu", "c" * 64, 10),
        row("一", "lishu", "c" * 64, 11),  # 同字同书体同图，去重
        row("一", "lishu", "d" * 64, 12),
        row("天", "jinwen", "e" * 64, 13),
        row("天", "jinwen", "e" * 64, 14),  # 同图去重
    ]


def test_split_characters_keeps_one_split_per_character():
    chars = [f"字{i}" for i in range(50)]
    split = split_characters(chars)
    assert set(split.values()) <= {"train", "val", "test"}
    assert sum(value == "train" for value in split.values()) == 35
    assert sum(value == "val" for value in split.values()) == 7
    assert sum(value == "test" for value in split.values()) == 8


def test_build_pairs_dedupes_target_images_and_keeps_split():
    pairs = build_pairs(rows(), target_styles=("lishu", "jinwen"))
    assert len(pairs) == 3
    assert {(pair["character"], pair["target_style"]) for pair in pairs} == {
        ("一", "lishu"), ("天", "jinwen")}
    assert len({pair["pair_id"] for pair in pairs}) == 3
    for character in {"一", "天"}:
        splits = {pair["split"] for pair in pairs if pair["character"] == character}
        assert len(splits) == 1
    assert all(pair["source_style"] == "kaishu_reference" for pair in pairs)


def test_write_pair_dataset_writes_manifest_and_stats(tmp_path):
    stats = write_pair_dataset(rows(), tmp_path, target_styles=("lishu", "jinwen"))
    assert stats["characters"] == 2 and stats["pairs"] == 3
    lines = [json.loads(line) for line in
             (tmp_path / "manifest.jsonl").read_text().splitlines()]
    assert len(lines) == 3
    assert all(line["source_image"] and line["target_image"] for line in lines)
    saved = json.loads((tmp_path / "stats.json").read_text())
    assert saved["pairs"] == 3
    assert saved["by_style"] == {"jinwen": 1, "lishu": 2}


def test_write_pair_dataset_rejects_missing_pairs(tmp_path):
    with pytest.raises(ValueError, match="没有可用"):
        write_pair_dataset([row("一", "kaishu_reference", "a" * 64, 1)], tmp_path)
