import hashlib
import json

import pytest
from PIL import Image

pytest.importorskip("torch")

from hanzi_evolution.ml.fontdiffuser_adapter import FontPairs, load_examples


def test_reference_comes_from_another_train_character(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    image = Image.new("RGBA", (86, 87), (0, 0, 0, 0))
    for x in range(20, 50):
        image.putpixel((x, 40), (0, 0, 0, 255))
    image.save(root / "glyph.png")
    sha = hashlib.sha256((root / "glyph.png").read_bytes()).hexdigest()
    rows = []
    for character, split in (("一", "train"), ("二", "train"), ("三", "test")):
        rows.append({
            "character": character, "split": split, "target_style": "jiaguwen",
            "target_url": "https://example.invalid/image?font=one",
            "source_image": "glyph.png", "target_image": "glyph.png",
            "source_sha256": sha, "target_sha256": sha,
            "pair_id": character,
        })
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows))
    examples, _, skipped = load_examples(manifest, root)
    assert len(examples) == 3 and not skipped
    for item in examples:
        assert all(ref["split"] == "train" for ref in item["refs"])
        assert all(ref["character"] != item["row"]["character"] for ref in item["refs"])
    item = FontPairs(examples, root, "test")[0]
    assert item["source"].shape == (3, 96, 96)
    assert item["source"][:, 0, 0].eq(1).all()
    assert item["source"].min() == -1

    rows[-1]["split"] = "train"
    rows[-1]["character"] = "二"
    rows[-2]["split"] = "test"
    manifest.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows))
    with pytest.raises(ValueError, match="跨 split"):
        load_examples(manifest, root)


def test_prototype_comparison_requires_same_character_style_and_distinct_font():
    from hanzi_evolution.ml.fontdiffuser_adapter import choose_prototype_comparison

    def item(pair_id, character, style, font, sha):
        return {"row": {"pair_id": pair_id, "character": character,
                        "target_style": style, "target_sha256": sha, "split": "test"},
                "font": font}

    target = item("target", "八", "jinwen", "font_a", "sha_a")
    same_font = item("same_font", "八", "jinwen", "font_a", "sha_b")
    same_image = item("same_image", "八", "jinwen", "font_b", "sha_a")
    other_char = item("other_char", "九", "jinwen", "font_b", "sha_c")
    other_style = item("other_style", "八", "lishu", "font_b", "sha_c")
    prototype = item("prototype", "八", "jinwen", "font_b", "sha_c")
    examples = [target, same_font, same_image, other_char, other_style, prototype]
    assert choose_prototype_comparison(examples, "test", "八", "jinwen", "target") == (target, prototype)
    assert choose_prototype_comparison(examples, "test", "八", "jinwen",
                                       "target", "prototype") == (target, prototype)
    with pytest.raises(ValueError, match="没有同字同书体"):
        choose_prototype_comparison(examples[:-1], "test", "八", "jinwen", "target")


def test_prototype_mode_uses_other_font_same_character(tmp_path):
    from hanzi_evolution.ml.fontdiffuser_adapter import glyph_tensor

    for name, x in (("modern.png", 10), ("target_a.png", 25), ("target_b.png", 40)):
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        for y in range(10, 50):
            point = (y, x) if name == "modern.png" else (x, y)
            image.putpixel(point, (0, 0, 0, 255))
        image.save(tmp_path / name)
    def example(pair_id, font, target, sha):
        row = {"pair_id": pair_id, "character": "八", "split": "train",
               "target_style": "jinwen", "source_image": "modern.png",
               "target_image": target, "target_sha256": sha}
        return {"row": row, "font": font, "refs": [row]}
    examples = [example("a", "font_a", "target_a.png", "sha_a"),
                example("b", "font_b", "target_b.png", "sha_b")]
    data = FontPairs(examples, tmp_path, "train", content_mode="prototype")
    assert len(data) == 2
    assert data[0]["source"].equal(glyph_tensor(tmp_path / "target_b.png"))
    assert data[1]["source"].equal(glyph_tensor(tmp_path / "target_a.png"))
    assert not data[0]["source"].equal(glyph_tensor(tmp_path / "modern.png"))
