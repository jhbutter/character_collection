import json

import pytest
from PIL import Image

pytest.importorskip("torch")
pytest.importorskip("diffusers")

from hanzi_evolution.ml.style_ddpm import PairDataset, image_tensor, load_manifest, make_model


def test_pair_dataset_preserves_split_and_alpha_ink(tmp_path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    image = Image.new("RGBA", (86, 87), (0, 0, 0, 0))
    for x in range(30, 56):
        for y in range(20, 70):
            image.putpixel((x, y), (0, 0, 0, 255))
    image.save(data_root / "glyph.png")
    row = {"character": "一", "split": "train", "source_image": "glyph.png",
           "target_image": "glyph.png", "target_style": "jiaguwen"}
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(json.dumps(row, ensure_ascii=False) + "\n")
    rows, _ = load_manifest(manifest, data_root, ("jiaguwen",))
    item = PairDataset(rows, data_root, "train", ("jiaguwen",))[0]
    assert item["source"].shape == (1, 64, 64)
    assert item["source"].min() == -1
    assert item["source"][0, 0, 0] == 1
    assert item["style_id"] == 0
    assert len(PairDataset(rows, data_root, "test", ("jiaguwen",))) == 0

    manifest.write_text(manifest.read_text() + json.dumps({**row, "split": "test"}) + "\n")
    with pytest.raises(ValueError, match="跨 split"):
        load_manifest(manifest, data_root, ("jiaguwen",))


def test_model_accepts_source_and_style_condition():
    import torch

    model = make_model(("jiaguwen", "jinwen"), (32, 32, 32, 32))
    with torch.no_grad():
        prediction = model(torch.zeros(1, 2, 64, 64), torch.tensor([10]),
                           class_labels=torch.tensor([1])).sample
    assert prediction.shape == (1, 1, 64, 64)
