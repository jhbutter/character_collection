import hashlib
import json
from types import SimpleNamespace

import pytest


@pytest.fixture
def expand_module():
    pytest.importorskip("selenium")
    pytest.importorskip("requests")
    pytest.importorskip("lxml")
    from hanzi_evolution.collection import expand
    return expand


def oracle_record():
    images = [
        {"img_id": 0, "desc": "字頭", "img_url": "https://example.invalid/head.png"},
        {"img_id": 1, "desc": "楷書字型", "img_url": "https://example.invalid/kai.png"},
    ]
    for index in range(2, 10):
        images.append({"img_id": index, "desc": f"出处{index}",
                       "img_url": f"https://example.invalid/{index}.png"})
    return {"id": 11, "charname": "一", "raw_head": "11", "imgList": images,
            "page_count": 1, "expected_glyph_count": 8}


def empty_html(head="一"):
    return (f'<form id="BasicFrom" action="/jinwen/PageResult/PageResult" method="post">'
            f'<input id="EudcFontChar" value="{head}"></form>'
            f'<div class="Information">共搜尋到 0 字</div>')


class ZeroDriver:
    page_source = ""
    current_url = "https://xiaoxue.iis.sinica.edu.tw/jinwen/"

    def check_page(self, html):
        return html


def test_oracle_sample_limits_to_five_and_skips_headers(expand_module):
    head, glyphs = expand_module.select_oracle_glyphs(oracle_record())
    assert head == "一"
    assert len(glyphs) == 5
    assert [glyph.local_key for glyph in glyphs] == ["2", "3", "4", "5", "6"]
    assert all(glyph.script_style == "jiaguwen" and glyph.character == "一" for glyph in glyphs)
    assert expand_module.available_oracle_images(oracle_record()) == 8


def test_oracle_sample_rejects_non_cjk_head(expand_module):
    record = oracle_record()
    record["charname"] = "11"
    with pytest.raises(ValueError, match="标准字头"):
        expand_module.select_oracle_glyphs(record)


def test_oracle_sample_rejects_missing_image_url(expand_module):
    record = oracle_record()
    record["imgList"][2]["img_url"] = ""
    with pytest.raises(ValueError, match="URL"):
        expand_module.select_oracle_glyphs(record)


def test_pending_downloads_skips_database_and_batch_cache(expand_module, tmp_path):
    urls = ["https://example.invalid/a.png", "https://example.invalid/b.png",
            "https://example.invalid/c.png"]
    glyphs = [SimpleNamespace(image_url=url) for url in urls]
    known = {urls[0]: "images/original/a.png"}
    token = hashlib.sha256(urls[1].encode()).hexdigest()
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / f"{token}.png").write_bytes(b"cached")
    assert expand_module.pending_downloads(glyphs, known, tmp_path) == 1


def test_collect_result_accepts_only_explicit_zero_page(expand_module):
    driver = ZeroDriver()
    driver.page_source = empty_html()
    first, glyphs, pages = expand_module.collect_result(
        driver, "jinwen", "一", html=empty_html(), allow_empty=True)
    assert first["empty"] is True
    assert first["source_record_id"] is None
    assert glyphs == [] and len(pages) == 1

    driver.page_source = empty_html()
    with pytest.raises(ValueError, match="字头"):
        expand_module.collect_result(driver, "jinwen", "一", html=empty_html())


def test_result_pages_reads_cached_zero_page_without_network(expand_module, tmp_path):
    html = empty_html()
    packet = [{"page": 1, "sha256": hashlib.sha256(html.encode()).hexdigest(), "html": html}]
    path = tmp_path / "pages" / "jinwen" / "U4E00.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(packet, ensure_ascii=False), encoding="utf-8")
    first, glyphs, pages = expand_module.result_pages(
        None, tmp_path, "jinwen", "一", allow_empty=True)
    assert first["empty"] is True
    assert glyphs == [] and len(pages) == 1


def test_run_stops_and_reports_when_preflight_is_blocked(expand_module, monkeypatch, tmp_path):
    monkeypatch.setattr(expand_module, "PROJECT", tmp_path)
    monkeypatch.setattr(expand_module, "preflight",
                        lambda *args: (_ for _ in ()).throw(expand_module.AccessRestricted("IP 封禁")))
    args = SimpleNamespace(folder=tmp_path / "batch", start_id=11, end_id=12, target=50,
                           max_images=100, interval=7, output=tmp_path / "dataset",
                           no_export=True, no_modern_reference=False)
    assert expand_module.run(args) == 2
    state = json.loads((tmp_path / "reports/expand_50.json").read_text(encoding="utf-8"))
    assert state["status"] == "blocked"
    assert state["downloaded_this_run"] == 0
    assert state["character_count"] == 0
    assert (tmp_path / "reports/expand_50.md").exists()
    assert (tmp_path / "batch/status.json").exists()
