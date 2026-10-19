"""把当前 10 字扩展到 50 字：甲骨文 11 号起顺序补采，每字最多 5 张。

设计约束（与 AGENTS.md 一致）：
- 默认 dry-run；只有显式 --execute 才联网。
- 单站串行、默认 7 秒、每批最多 100 张新图；401/403/429/5xx/受限页立即停止。
- 甲骨文每字最多 5 张；跨来源仍按“汉字 + 字体阶段”合计最多 5 张。
- 目标按“有图片的字头数”计算，不把尝试次数当成完成字数。
- 分两阶段：先补甲骨文到 50 字，再为这 50 字补四个跨来源。
- 任何批次中断后重复执行同一命令即可续跑；不覆盖既有证据。
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unicodedata

import requests
from sqlalchemy import func, select

from .common import PROJECT, is_stop_error, save_json
from .complete_ten import result_pages
from .cross_source import attach_images, collect_result, process_reference
from http_driver import HTTPDriver
from read_font import (AccessRestricted, PageLayoutError, check_page,
                       get_xiaozhuan_list_url, preflight)
from hanzi_evolution import schema_v1 as schema
from hanzi_evolution.adapters import GlyphInput, RecordInput, SourceInput
from hanzi_evolution.db import open_db
from hanzi_evolution.store import (export_rows, import_records, now, report,
                                   write_directory_export)
from hanzi_evolution.xiaoxue import COLLECTION_NAMES, select_missing_styles

START_ID = 11
DEFAULT_END_ID = 60
TARGET_CHARACTERS = 50
ORACLE_LIMIT = 5
SKIP_ORACLE_DESC = {"字頭", "楷書字型"}


class BudgetReached(RuntimeError):
    """本批 100 张新图预算用完；当前记录不写入，等待下次续跑。"""


def is_cjk_character(value):
    return bool(value) and len(value) == 1 and unicodedata.name(value, "").startswith(
        "CJK UNIFIED IDEOGRAPH")


def select_oracle_glyphs(record, limit=ORACLE_LIMIT):
    """从甲骨文页面记录中选前 limit 张字形，跳过字头和楷书字型。"""
    head = record.get("charname")
    if not is_cjk_character(head):
        raise ValueError("甲骨文记录没有可确认的单字标准字头")
    glyphs = []
    for image in record.get("imgList", []):
        if image.get("desc", "").strip() in SKIP_ORACLE_DESC:
            continue
        key = str(image.get("img_id", ""))
        if not key.isdecimal():
            raise ValueError("甲骨文图片编号必须为非负整数")
        url = image.get("img_url")
        if not url:
            raise ValueError("甲骨文图片缺少来源 URL")
        glyphs.append(GlyphInput(local_key=key, character=head, script_style="jiaguwen",
                                 citation=image.get("desc") or None, image_url=url))
        if len(glyphs) >= limit:
            break
    if not glyphs:
        raise ValueError("甲骨文记录没有可用字形")
    return head, glyphs


def available_oracle_images(record):
    return sum(1 for image in record.get("imgList", [])
               if image.get("desc", "").strip() not in SKIP_ORACLE_DESC)


def pending_downloads(glyphs, known_images, folder):
    """统计尚未在数据库或批次缓存中的图片数，用于下载前预算检查。"""
    pending = 0
    for glyph in glyphs:
        url = glyph.image_url
        if not url:
            raise ValueError("字形缺少图片 URL")
        if url in known_images:
            continue
        token = hashlib.sha256(url.encode()).hexdigest()
        if (Path(folder) / "images" / f"{token}.png").exists():
            continue
        pending += 1
    return pending


def character_count(engine):
    statement = select(func.count(func.distinct(schema.glyph.c.character_id))).select_from(
        schema.glyph.join(schema.glyph_image))
    with engine.connect() as conn:
        return conn.scalar(statement) or 0


def load_known_images(engine):
    return {row["original_url"]: row["image_path"] for row in export_rows(engine, True, True)
            if row["original_url"] and row["image_path"]}


def oracle_exists(engine, index):
    with engine.connect() as conn:
        return conn.scalar(select(schema.source_record.c.id).where(
            schema.source_record.c.source_id == "sinica_xiaoxue_jiaguwen",
            schema.source_record.c.local_id == str(index))) is not None


def oracle_character(engine, index):
    statement = (select(schema.character.c.label)
                 .select_from(schema.source_record.join(schema.glyph).join(schema.character))
                 .where(schema.source_record.c.source_id == "sinica_xiaoxue_jiaguwen",
                        schema.source_record.c.local_id == str(index)))
    with engine.connect() as conn:
        return conn.scalar(statement)


def get_oracle_record(driver, query_args, folder, index):
    path = folder / "records" / "jiaguwen" / f"{index}.json"
    if path.exists():
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("id") != index:
            raise ValueError("甲骨文缓存编号不一致")
        if is_cjk_character(record.get("charname")):
            return record
        # 旧缓存可能把 PUA 外字当成字头；保留原始页面，但重新解析一次。

    record = get_xiaozhuan_list_url(driver, query_args, folder / "records" / "jiaguwen" / str(index), index)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return record


def import_oracle(engine, source, record, index, folder, known_images, state, args, driver):
    head, glyphs = select_oracle_glyphs(record)
    pending = pending_downloads(glyphs, known_images, folder)
    if state["downloaded_this_run"] + pending > args.max_images:
        raise BudgetReached("本批新图预算不足以完成该甲骨文记录，下次续跑")
    glyphs = attach_images(glyphs, driver, folder, known_images, state, args)
    normalized = RecordInput(local_id=str(index), source_url=record.get("source_url"),
                             raw_head=record.get("raw_head"), glyphs=glyphs)
    packet = {"source": "jiaguwen", "oracle_id": index,
              "sampling": {"policy": "oracle_first_n", "limit": ORACLE_LIMIT,
                           "available": available_oracle_images(record),
                           "selected": len(glyphs)},
              "page_record": record, "normalized": normalized.model_dump()}
    raw = (json.dumps(packet, ensure_ascii=False, sort_keys=True) + "\n").encode()
    imported = import_records(engine, PROJECT / "data", source, [normalized], raw,
                              "expand50-jiaguwen-v1", PROJECT / "data")
    return {"id": index, "character": head, "status": "imported",
            "pending_downloads": pending, "selected": len(glyphs), **imported}


def import_collection(engine, driver, source, collection, character, folder,
                      known_images, state, args):
    first, glyphs, pages = result_pages(driver, folder, collection, character, allow_empty=True)
    if first.get("empty"):
        return {"source": collection, "status": "no_result", "available": 0, "selected": 0}
    selected = select_missing_styles(glyphs, export_rows(engine, True))
    pending = pending_downloads(selected, known_images, folder)
    if state["downloaded_this_run"] + pending > args.max_images:
        raise BudgetReached("本批新图预算不足以完成该跨来源记录，下次续跑")
    selected = attach_images(selected, driver, folder, known_images, state, args)
    result = {"source": collection, "status": "complete", "available": len(glyphs),
              "selected": len(selected),
              "styles": dict(Counter(glyph.script_style for glyph in selected))}
    if selected:
        record = RecordInput(local_id=str(first["source_record_id"]) + ":expand50-v1",
                             source_url=f"https://xiaoxue.iis.sinica.edu.tw/{collection}/",
                             raw_head=str(first["source_record_id"]), glyphs=selected)
        packet = {"source": collection, "query_character": character,
                  "source_record_id": first["source_record_id"],
                  "sampling": {"policy": "global_character_style_max5",
                               "available": len(glyphs), "selected": len(selected)},
                  "pages": pages, "normalized": record.model_dump()}
        raw = (json.dumps(packet, ensure_ascii=False, sort_keys=True) + "\n").encode()
        result.update(import_records(engine, PROJECT / "data", source, [record], raw,
                                     "expand50-forms-v1", PROJECT / "data"))
    else:
        result["status"] = "already_full"
    if first.get("modern_reference") and not args.no_modern_reference:
        links = {character: {"yanbian": "https://xiaoxue.iis.sinica.edu.tw/yanbian/"}}
        process_reference(engine, driver, character, first, {"pages": pages},
                          links, folder, known_images, state, args)
    return result


def collect_oracle(engine, driver, query_args, args, state, known_images, folder):
    source = SourceInput.model_validate_json(
        (PROJECT / "config/xiaoxue_jiaguwen.json").read_text(encoding="utf-8"))
    for index in range(args.start_id, args.end_id + 1):
        if character_count(engine) >= args.target:
            state["status"] = "oracle_done"
            return
        if oracle_exists(engine, index):
            head = oracle_character(engine, index)
            state["oracle_records"].append({"id": index, "character": head,
                                            "status": "already_imported"})
            save_json(folder / "status.json", state)
            continue
        item = {"id": index}
        try:
            record = get_oracle_record(driver, query_args, folder, index)
            item = import_oracle(engine, source, record, index, folder,
                                 known_images, state, args, driver)
        except BudgetReached as error:
            state.update(status="budget_reached", phase="oracle", resume_id=index, error=str(error))
            return
        except AccessRestricted as error:
            state.update(status="blocked", phase="oracle", resume_id=index,
                         error_type=type(error).__name__, error=str(error))
            return
        except requests.RequestException as error:
            if is_stop_error(error):
                state.update(status="blocked", phase="oracle", resume_id=index,
                             error_type=type(error).__name__, error=str(error))
                return
            item.update(status="failed", error_type=type(error).__name__, error=str(error))
        except (PageLayoutError, ValueError, OSError, RuntimeError) as error:
            if is_stop_error(error):
                state.update(status="blocked", phase="oracle", resume_id=index,
                             error_type=type(error).__name__, error=str(error))
                return
            item.update(status="failed", error_type=type(error).__name__, error=str(error))
        state["oracle_records"].append(item)
        save_json(folder / "status.json", state)
        print(json.dumps(item, ensure_ascii=False), flush=True)
    state["status"] = "oracle_done" if character_count(engine) >= args.target else "oracle_shortfall"


def collect_cross(engine, driver, args, state, known_images, folder):
    source_by_collection = {
        collection: SourceInput.model_validate_json(
            (PROJECT / f"config/xiaoxue_{collection}.json").read_text(encoding="utf-8"))
        for collection in COLLECTION_NAMES
    }
    with engine.connect() as conn:
        characters = [row[1] for row in conn.execute(
            select(schema.character.c.id, schema.character.c.label)
            .select_from(schema.character.join(schema.glyph).join(schema.glyph_image))
            .distinct().order_by(schema.character.c.id))]
    characters = characters[:args.target]
    if len(characters) < args.target:
        state.update(status="shortfall", phase="cross",
                     error=f"仅有 {len(characters)} 个有图字头，未达到 {args.target}")
        return
    for character in characters:
        item = {"character": character, "collections": {}}
        for collection in COLLECTION_NAMES:
            try:
                result = import_collection(engine, driver, source_by_collection[collection],
                                           collection, character, folder,
                                           known_images, state, args)
            except BudgetReached as error:
                state.update(status="budget_reached", phase="cross",
                             resume_character=character, error=str(error))
                return
            except AccessRestricted as error:
                state.update(status="blocked", phase="cross", resume_character=character,
                             error_type=type(error).__name__, error=str(error))
                return
            except requests.RequestException as error:
                if is_stop_error(error):
                    state.update(status="blocked", phase="cross", resume_character=character,
                                 error_type=type(error).__name__, error=str(error))
                    return
                result = {"source": collection, "status": "failed",
                          "error_type": type(error).__name__, "error": str(error)}
            except (PageLayoutError, ValueError, OSError, RuntimeError) as error:
                if is_stop_error(error):
                    state.update(status="blocked", phase="cross", resume_character=character,
                                 error_type=type(error).__name__, error=str(error))
                    return
                result = {"source": collection, "status": "failed",
                          "error_type": type(error).__name__, "error": str(error)}
            item["collections"][collection] = result
            state["cross_records"].append({"character": character, **result})
            save_json(folder / "status.json", state)
            print(json.dumps({"character": character, **result}, ensure_ascii=False), flush=True)
        state["characters"].append(item)
        save_json(folder / "status.json", state)
    state["status"] = "cross_done"


def log_count(folder, name):
    path = Path(folder) / name
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def network_record_count(folder):
    """批次累计的查询与下载记录数，含一次 robots 探测；不是精确 HTTP 计数。"""
    preflight = 1 if (Path(folder) / "preflight.json").exists() else 0
    return preflight + log_count(folder, "requests.jsonl") + log_count(folder, "downloads.jsonl")


def write_markdown(state, path):
    lines = ["# 扩展到 50 字采集报告", "",
             f"- 状态：`{state['status']}`",
             f"- 阶段：`{state.get('phase', 'none')}`",
             f"- 目标有图字头：{state.get('target')}",
             f"- 实际有图字头：{state.get('character_count', 0)}",
             f"- 本次新下载图片：{state.get('downloaded_this_run', 0)}",
             f"- 批次累计网络记录：{state.get('network_records', 0)}",
             f"- 开始：{state.get('started_at')}",
             f"- 结束：{state.get('finished_at')}", ""]
    quality = state.get("quality") or {}
    if quality:
        lines += [f"- 数据库字形关联：{quality.get('real_glyph_count')}",
                  f"- 不同原图：{quality.get('real_image_count')}",
                  f"- 图像有效率：{quality.get('image_validity_rate')}",
                  f"- 来源可追溯率：{quality.get('source_traceability_rate')}", ""]
    lines += ["## 甲骨文阶段", "", "| 编号 | 汉字 | 状态 | 选中 | 说明 |", "| --- | --- | --- | --- | --- |"]
    for row in state.get("oracle_records", []):
        lines.append(f"| {row.get('id')} | {row.get('character') or ''} | {row.get('status')} | "
                     f"{row.get('selected', '')} | {row.get('error') or ''} |")
    lines += ["", "## 跨来源阶段", "", "| 汉字 | 来源 | 状态 | 可用 | 选中 | 说明 |",
              "| --- | --- | --- | --- | --- | --- |"]
    for row in state.get("cross_records", []):
        lines.append(f"| {row.get('character')} | {row.get('source')} | {row.get('status')} | "
                     f"{row.get('available', '')} | {row.get('selected', '')} | {row.get('error') or ''} |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args):
    folder = args.folder.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    engine = open_db(PROJECT / "data/hanzi.sqlite")
    state = {"started_at": now(), "status": "running", "phase": "oracle",
             "target": args.target, "range": [args.start_id, args.end_id],
             "oracle_limit": ORACLE_LIMIT, "downloaded_this_run": 0,
             "oracle_records": [], "cross_records": [], "characters": []}
    driver = None
    query_args = SimpleNamespace(
        target_url="https://xiaoxue.iis.sinica.edu.tw/jiaguwen/?ZiOrder=%d",
        start_idx=args.start_id, size=64, interval=args.interval, max_pages=10,
        user_agent="HanziResearchExpand50/0.1 (+https://github.com/EvaWang/xiaoxue_crawler)")
    try:
        preflight(query_args, folder)
        driver = HTTPDriver(query_args, folder, check_page)
        known_images = load_known_images(engine)
        collect_oracle(engine, driver, query_args, args, state, known_images, folder)
        if state["status"] == "oracle_done":
            state["phase"] = "cross"
            collect_cross(engine, driver, args, state, known_images, folder)
        if state["status"] == "cross_done":
            state["status"] = "finished" if character_count(engine) >= args.target else "shortfall"
    except (RuntimeError, requests.RequestException, ValueError, OSError) as error:
        state.update(status="blocked" if is_stop_error(error) else "failed",
                     error_type=type(error).__name__, error=str(error))
    finally:
        if driver:
            driver.quit()
        state["finished_at"] = now()
        state["character_count"] = character_count(engine)
        state["network_records"] = network_record_count(folder)
        recorded = {row.get("id") for row in state["oracle_records"]}
        state["not_attempted_ids"] = [index for index in range(args.start_id, args.end_id + 1)
                                      if index not in recorded and not oracle_exists(engine, index)]
        state["quality"] = report(engine, PROJECT / "data")
        save_json(folder / "status.json", state)
        save_json(PROJECT / "reports/expand_50.json", state)
        write_markdown(state, PROJECT / "reports/expand_50.md")
        if state["status"] == "finished" and not args.no_export:
            try:
                state["export"] = write_directory_export(
                    export_rows(engine, True), PROJECT / "data", args.output, True)
            except (ValueError, OSError) as error:
                state["export_error"] = str(error)
                state["status"] = "export_error"
            save_json(folder / "status.json", state)
            save_json(PROJECT / "reports/expand_50.json", state)
        engine.dispose()
    print(json.dumps({"status": state["status"], "character_count": state["character_count"],
                      "downloaded": state["downloaded_this_run"],
                      "network_records": state["network_records"]}, ensure_ascii=False), flush=True)
    return 0 if state["status"] == "finished" else 2


def main():
    parser = argparse.ArgumentParser(description="扩展当前 10 字到 50 字：甲骨文顺序补采 + 四来源")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--start-id", type=int, default=START_ID)
    parser.add_argument("--end-id", type=int, default=DEFAULT_END_ID,
                        help="默认 60：11–50 为主，失败时用 51–60 补足到 50 字")
    parser.add_argument("--target", type=int, default=TARGET_CHARACTERS)
    parser.add_argument("--max-images", type=int, default=100)
    parser.add_argument("--interval", type=float, default=7)
    parser.add_argument("--folder", type=Path, default=PROJECT / "data/batches/expand_50")
    parser.add_argument("--output", type=Path, default=PROJECT / "data/dataset_50")
    parser.add_argument("--no-modern-reference", action="store_true")
    parser.add_argument("--no-export", action="store_true")
    args = parser.parse_args()
    if args.start_id < 1 or not 0 <= args.end_id - args.start_id < 100:
        parser.error("编号范围必须从 1 开始且最多 100 个编号")
    if not 1 <= args.max_images <= 100:
        parser.error("每批最多 100 张新图")
    if args.interval < 5:
        parser.error("间隔至少 5 秒")
    if not 1 <= args.target <= 100:
        parser.error("目标字数必须在 1 至 100 之间")
    if not args.execute:
        print(json.dumps({"status": "dry_run", "range": [args.start_id, args.end_id],
                          "target": args.target, "oracle_limit": ORACLE_LIMIT,
                          "max_images": args.max_images, "network_requests": 0,
                          "output": str(args.output)}, ensure_ascii=False))
        return 0
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
