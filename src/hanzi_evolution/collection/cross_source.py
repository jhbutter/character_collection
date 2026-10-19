import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from types import SimpleNamespace
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import requests
from sqlalchemy import select

from .common import PROJECT, is_stop_error, save_json
from read_font import check_page, preflight
from http_driver import HTTPDriver
from download_img import validate_image, fetch_png
from selenium.common.exceptions import NoSuchElementException
from hanzi_evolution import schema_v1 as schema
from hanzi_evolution.adapters import RecordInput, SourceInput
from hanzi_evolution.db import open_db
from hanzi_evolution.store import import_records, export_rows, write_directory_export, report, now
from hanzi_evolution.xiaoxue import (COLLECTION_NAMES, parse_result_page,
    parse_result_page_or_empty, sample_by_style, read_cached_sample)


AUDITED = {"一": "one", "天": "tian"}


def official_links(engine, character):
    with engine.connect() as conn:
        raw_path = conn.scalar(select(schema.source_record.c.raw_path)
            .select_from(schema.source_record.join(schema.glyph).join(schema.character))
            .where(schema.source_record.c.source_id == "sinica_xiaoxue_jiaguwen", schema.character.c.label == character))
    if not raw_path:
        raise ValueError("缺少已核验的甲骨文字头来源记录")
    record = json.loads((PROJECT / "data" / raw_path).read_text())
    for digest in record["raw_sha256"]:
        for path in (PROJECT / "data").rglob(digest + ".html"):
            html = path.read_text(encoding="utf-8")
            if hashlib.sha256(html.encode()).hexdigest() != digest:
                raise ValueError("来源网页哈希不一致")
            soup = BeautifulSoup(html, "lxml")
            heads = {chr(int(match[1], 16)) for image in soup.select("img.charValue")
                     if (match := re.fullmatch(r"&0\.([0-9A-Fa-f]+);", image.get("alt", "")))}
            if character not in heads:
                continue
            links = {}
            for name in COLLECTION_NAMES:
                anchor = next((a for a in soup.select("a[href]") if a["href"].startswith(f"/{name}?")), None)
                if anchor is not None:
                    links[name] = urljoin("https://xiaoxue.iis.sinica.edu.tw", anchor["href"])
            if len(links) == len(COLLECTION_NAMES):
                return links
    raise ValueError("缺少能追溯到该字头的官方跨库链接")


def collect_result(driver, collection, character, max_pages=10, html=None, allow_empty=False):
    audit = PROJECT / "data/raw/cross_source_audit"
    if html is None:
        html = (audit / f"{collection}_{AUDITED[character]}_result.html").read_text(encoding="utf-8")
    action = BeautifulSoup(html, "lxml").find("form")["action"]
    driver.current_url = urljoin("https://xiaoxue.iis.sinica.edu.tw", action)
    driver.page_source = html
    all_glyphs, seen_pages, seen_keys, pages = [], set(), set(), []
    first = None
    parse = parse_result_page_or_empty if allow_empty else parse_result_page
    for page_number in range(1, max_pages + 1):
        html = driver.page_source
        driver.check_page(html)
        digest = hashlib.sha256(html.encode()).hexdigest()
        if digest in seen_pages:
            raise ValueError("跨库查询返回重复页面")
        seen_pages.add(digest)
        parsed = parse(html, collection, character, page_number, driver.current_url)
        if first is None:
            first = parsed
            if first.get("empty"):
                pages.append({"page": page_number, "sha256": digest, "html": html})
                return first, [], pages
            if first["page_count"] > max_pages:
                raise ValueError("结果页数超过MVP上限")
        elif any(parsed[key] != first[key] for key in ("source_record_id", "expected_glyph_count", "page_count")):
            raise ValueError("翻页期间字头编号或结果数量变化")
        for glyph in parsed["glyphs"]:
            if glyph.local_key in seen_keys:
                raise ValueError("跨页出现重复字形实例")
            seen_keys.add(glyph.local_key)
            all_glyphs.append(glyph)
        pages.append({"page": page_number, "sha256": digest, "html": html})
        try:
            next_page = driver.find_element(None, "下一頁")
        except NoSuchElementException:
            if len(pages) != first["page_count"] or len(all_glyphs) != first["expected_glyph_count"]:
                raise ValueError("跨库结果的实际页数或字形数不完整")
            return first, all_glyphs, pages
        if page_number == max_pages:
            raise ValueError("到达分页上限")
        next_page.click()
    raise ValueError("分页未完成")


def attach_images(glyphs, driver, folder, known_images, state, args):
    result = []
    for glyph in glyphs:
        url = glyph.image_url
        if getattr(driver.args, "robots", None) and not driver.args.robots.can_fetch(driver.args.user_agent, url):
            raise RuntimeError("robots 不允许图片地址，停止MVP")
        relative = known_images.get(url)
        if relative:
            target = PROJECT / "data" / relative
            metadata = validate_image(target.read_bytes(), "image/png")
        else:
            token = hashlib.sha256(url.encode()).hexdigest()
            target = folder / "images" / f"{token}.png"
            if target.exists():
                metadata = validate_image(target.read_bytes(), "image/png")
            else:
                if state["downloaded_this_run"] >= args.max_images:
                    raise RuntimeError("达到MVP图片预算，停止下载")
                time.sleep(max(0, driver.args.interval - (time.monotonic() - driver.last_request)))
                driver.last_request = time.monotonic()
                data, metadata = fetch_png(driver.session, url)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.with_suffix(".part").write_bytes(data)
                target.with_suffix(".part").replace(target)
                state["downloaded_this_run"] += 1
            relative = target.resolve().relative_to(PROJECT / "data").as_posix()
            known_images[url] = relative
        with (folder / "downloads.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"character": glyph.character, "style": glyph.script_style,
                "image_url": url, "image_path": relative, "time": now(), **metadata}, ensure_ascii=False) + "\n")
        result.append(glyph.model_copy(update={"image_path": relative}))
        save_json(folder / "status.json", state)
        print(json.dumps({"event": "image_ready", "character": glyph.character,
            "style": glyph.script_style, "new_downloads": state["downloaded_this_run"]}, ensure_ascii=False), flush=True)
    return result


def process_case(engine, driver, collection, character, source, links, folder, known_images, state, args):
    raw_path = folder / "records" / collection / f"U{ord(character):04X}.jsonl"
    if raw_path.exists():
        record, packet, raw = read_cached_sample(raw_path, collection, character, args.per_style)
        first = parse_result_page(packet["pages"][0]["html"], collection, character)
    else:
        first, all_glyphs, pages = collect_result(driver, collection, character)
        selected = attach_images(sample_by_style(all_glyphs, args.per_style), driver, folder, known_images, state, args)
        record = RecordInput(local_id=first["source_record_id"], source_url=links[character][collection],
            raw_head=first["source_record_id"], glyphs=selected)
        packet = {"source": collection, "query_character": character, "source_record_id": first["source_record_id"],
            "sampling": {"type": "mvp_per_style_first_n", "per_style_limit": args.per_style,
                         "available_glyph_count": len(all_glyphs), "retained_glyph_count": len(selected)},
            "pages": pages, "normalized": record.model_dump()}
        raw = (json.dumps(packet, ensure_ascii=False, sort_keys=True) + "\n").encode()
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(raw)
    imported = import_records(engine, PROJECT / "data", source, [record], raw, "xiaoxue-forms-v1", PROJECT / "data")
    item = {"source": collection, "character": character, "source_record_id": record.local_id,
        "pages": len(packet["pages"]), "available": packet["sampling"]["available_glyph_count"],
        "sampled": len(record.glyphs), "styles": dict(Counter(g.script_style for g in record.glyphs)),
        "status": "already_imported" if imported["records_skipped"] else "sample_imported", **imported}
    return item, first, packet


def process_reference(engine, driver, character, first, packet, links, folder, known_images, state, args):
    source = SourceInput.model_validate_json((PROJECT / "config/xiaoxue_modern_reference.json").read_text())
    with engine.connect() as conn:
        existing = conn.execute(select(schema.source_record).where(
            schema.source_record.c.source_id == source.id,
            schema.source_record.c.local_id == first["source_record_id"])).mappings().first()
    if existing:
        raw = (PROJECT / "data" / existing["raw_path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != existing["raw_sha256"]:
            raise ValueError("现代参考原始记录哈希不一致")
        record = RecordInput.model_validate(json.loads(raw)["normalized"])
    else:
        glyphs = attach_images([first["modern_reference"]], driver, folder, known_images, state, args)
        record = RecordInput(local_id=first["source_record_id"], source_url=links[character]["yanbian"],
            raw_head=first["source_record_id"], glyphs=glyphs)
        raw = (json.dumps({"asset_role": "modern_reference_not_historical_sample",
            "page_sha256": packet["pages"][0]["sha256"], "normalized": record.model_dump()},
            ensure_ascii=False, sort_keys=True) + "\n").encode()
    import_records(engine, PROJECT / "data", source, [record], raw, "xiaoxue-forms-v1", PROJECT / "data")


def run(args):
    folder = args.folder.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    engine = open_db(PROJECT / "data/hanzi.sqlite")
    state = {"started_at": now(), "characters": list(AUDITED), "sampling_per_source_style": args.per_style,
             "downloaded_this_run": 0, "status": "running", "records": []}
    query_args = SimpleNamespace(user_agent="HanziResearchMVP/0.1 (+https://github.com/EvaWang/xiaoxue_crawler)",
        interval=7, start_idx=1, target_url="https://xiaoxue.iis.sinica.edu.tw/jinwen/?kaiOrder=%d")
    driver = None
    try:
        links = {character: official_links(engine, character) for character in AUDITED}
        preflight(query_args, folder)
        driver = HTTPDriver(query_args, folder, check_page)
        with engine.connect() as conn:
            known_images = {row.original_url: row.path for row in conn.execute(
                select(schema.glyph_image.c.original_url, schema.image_asset.c.path)
                .select_from(schema.glyph_image.join(schema.image_asset)))}
        for collection in COLLECTION_NAMES:
            source = SourceInput.model_validate_json((PROJECT / f"config/xiaoxue_{collection}.json").read_text())
            for character in AUDITED:
                item, first, packet = process_case(engine, driver, collection, character, source,
                    links, folder, known_images, state, args)
                state["records"].append(item)
                save_json(folder / "status.json", state)
                print(json.dumps(item, ensure_ascii=False), flush=True)
                if first["modern_reference"] is not None:
                    process_reference(engine, driver, character, first, packet, links, folder, known_images, state, args)
        state["status"] = "finished"
    except (RuntimeError, requests.RequestException, ValueError, OSError) as error:
        state.update(status="blocked" if is_stop_error(error) else "failed", error_type=type(error).__name__, error=str(error))
    finally:
        if driver:
            driver.quit()
        state["finished_at"] = now()
        state["quality"] = report(engine, PROJECT / "data")
        save_json(folder / "status.json", state)
        save_json(PROJECT / "reports/cross_source_mvp.json", state)
        save_json(PROJECT / "reports/current_quality.json", state["quality"])
        if state["status"] == "finished":
            state["export"] = write_directory_export(export_rows(engine, include_quarantine=True), PROJECT / "data", args.output, include_quarantine=True)
            save_json(folder / "status.json", state)
            save_json(PROJECT / "reports/cross_source_mvp.json", state)
        engine.dispose()
    print(json.dumps(state, ensure_ascii=False, indent=2), flush=True)
    return 0 if state["status"] == "finished" else 2


def main():
    parser = argparse.ArgumentParser(description="跨来源MVP：完整校验一/天的结果页，每来源每分类限量抽样")
    parser.add_argument("--per-style", type=int, default=2)
    parser.add_argument("--max-images", type=int, default=100)
    parser.add_argument("--folder", type=Path, default=PROJECT / "data/batches/cross_source_mvp")
    parser.add_argument("--output", type=Path, default=PROJECT / "data/dataset_cross_source_mvp")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.per_style <= 5 or not 1 <= args.max_images <= 100:
        parser.error("每来源每分类1至5张，每批最多100张新图")
    if not args.execute:
        print(json.dumps({"status": "dry_run", "characters": list(AUDITED), "sources": list(COLLECTION_NAMES)}, ensure_ascii=False))
        return 0
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
