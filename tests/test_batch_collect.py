import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def batch_module():
    pytest.importorskip("selenium")
    pytest.importorskip("requests")
    pytest.importorskip("lxml")
    from hanzi_evolution.collection import batch
    return batch


def test_access_restriction_stops_remaining_heads(batch_module, monkeypatch, tmp_path):
    module = batch_module
    monkeypatch.setattr(module, "PROJECT", tmp_path)
    config = tmp_path / "config/xiaoxue_jiaguwen.json"
    config.parent.mkdir()
    config.write_text(json.dumps({"id": "fixture", "name": "合成测试", "is_test": True}))
    monkeypatch.setattr(module, "preflight", lambda *args: None)
    monkeypatch.setattr(module, "HTTPDriver", lambda *args: SimpleNamespace(quit=lambda: None))
    called = []
    def get_record(driver, args, folder, index):
        called.append(index)
        raise module.AccessRestricted("受限")
    monkeypatch.setattr(module, "get_xiaozhuan_list_url", get_record)
    args = SimpleNamespace(folder=tmp_path / "batch", start=1, end=3, max_images=3, interval=7, output=None)
    assert module.run(args) == 2
    state = json.loads((args.folder / "status.json").read_text())
    assert called == [1]
    assert state["status"] == "blocked"
    assert state["not_attempted_ids"] == [2, 3]
    assert state["quality"]["real_glyph_count"] == 0


def test_layout_failure_is_recorded_and_next_head_attempted(batch_module, monkeypatch, tmp_path):
    module = batch_module
    monkeypatch.setattr(module, "PROJECT", tmp_path)
    config = tmp_path / "config/xiaoxue_jiaguwen.json"
    config.parent.mkdir()
    config.write_text(json.dumps({"id": "fixture", "name": "合成测试", "is_test": True}))
    monkeypatch.setattr(module, "preflight", lambda *args: None)
    monkeypatch.setattr(module, "HTTPDriver", lambda *args: SimpleNamespace(quit=lambda: None))
    called = []
    def get_record(driver, args, folder, index):
        called.append(index)
        raise module.PageLayoutError("未验证多页")
    monkeypatch.setattr(module, "get_xiaozhuan_list_url", get_record)
    args = SimpleNamespace(folder=tmp_path / "batch", start=1, end=3, max_images=3, interval=7, output=None)
    assert module.run(args) == 0
    state = json.loads((args.folder / "status.json").read_text())
    assert called == [1, 2, 3]
    assert all(row["status"] == "failed" for row in state["records"])
    assert state["not_attempted_ids"] == []
