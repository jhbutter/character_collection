import argparse
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import requests
from sqlalchemy import select

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "thirdparty/xiaoxue_crawler"))
from read_font import AccessRestricted, PageLayoutError, check_page, get_xiaozhuan_list_url, preflight
from http_driver import HTTPDriver
from download_img import validate_image
from hanzi_evolution import schema_v1 as schema
from hanzi_evolution.adapters import LegacyAdapter, SourceInput
from hanzi_evolution.db import open_db
from hanzi_evolution.store import import_records, now, report, write_directory_export, export_rows


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def is_stop_error(error):
    if isinstance(error, AccessRestricted):
        return True
    if isinstance(error, requests.HTTPError):
        return error.response is not None and (error.response.status_code in {401, 403, 429} or error.response.status_code >= 500)
    return isinstance(error, (requests.ConnectionError, requests.Timeout))


def run(args):
    folder = args.folder
    folder.mkdir(parents=True, exist_ok=True)
    state_path = folder / "status.json"
    state = {"started_at": now(), "range": [args.start, args.end], "requested_heads": args.end - args.start + 1,
             "download_limit": args.max_images, "downloaded_this_run": 0, "records": [], "status": "running"}
    source = SourceInput.model_validate_json((PROJECT / "config/xiaoxue_jiaguwen.json").read_text())
    engine = open_db(PROJECT / "data/hanzi.sqlite")
    driver = None
    query_args = SimpleNamespace(target_url="https://xiaoxue.iis.sinica.edu.tw/jiaguwen/?ZiOrder=%d",
        start_idx=args.start, size=64, interval=args.interval, max_pages=10,
        user_agent="HanziResearchPilot/0.1 (+https://github.com/EvaWang/xiaoxue_crawler)")
    save_json(state_path, state)
    try:
        preflight(query_args, folder)
        driver = HTTPDriver(query_args, folder, check_page)
        for index in range(args.start, args.end + 1):
            item = {"source_record_id": index, "started_at": now()}
            with engine.connect() as conn:
                exists = conn.scalar(select(schema.source_record.c.id).where(
                    schema.source_record.c.source_id == source.id, schema.source_record.c.local_id == str(index)))
            if exists is not None:
                item.update(status="already_in_database")
                state["records"].append(item)
                save_json(state_path, state)
                print(json.dumps(item, ensure_ascii=False), flush=True)
                continue
            try:
                record_folder = folder / "records" / str(index)
                path = record_folder / "record.jsonl"
                if path.exists():
                    record = json.loads(path.read_text())
                else:
                    record = get_xiaozhuan_list_url(driver, query_args, record_folder, index)
                    path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
                images = [image for image in record["imgList"] if image["desc"].strip() not in {"字頭", "楷書字型"}]
                image_folder = record_folder / "img"
                image_folder.mkdir(exist_ok=True)
                pending = sum(not (image_folder / f"{index}_{image['img_id']}.png").exists() for image in images)
                if state["downloaded_this_run"] + pending > args.max_images:
                    item.update(status="image_budget_exceeded", image_count=len(images))
                    state["status"] = "budget_reached"
                    state["records"].append(item)
                    save_json(state_path, state)
                    break
                for image in images:
                    url = image["img_url"]
                    if getattr(query_args, "robots", None) and not query_args.robots.can_fetch(query_args.user_agent, url):
                        raise AccessRestricted("robots 不允许图片地址")
                    target = image_folder / f"{index}_{image['img_id']}.png"
                    if target.exists():
                        metadata = validate_image(target.read_bytes(), "image/png")
                    else:
                        time.sleep(max(0, query_args.interval - (time.monotonic() - driver.last_request)))
                        driver.last_request = time.monotonic()
                        with driver.session.get(url, stream=True, timeout=25, allow_redirects=False) as response:
                            response.raise_for_status()
                            mime = response.headers.get("Content-Type", "")
                            if response.status_code != 200 or not mime.lower().startswith("image/"):
                                check_page(response.text)
                                raise RuntimeError("图片请求不是成功图像响应")
                            chunks, size = [], 0
                            for chunk in response.iter_content(65536):
                                size += len(chunk)
                                if size > 20 * 1024 * 1024:
                                    raise ValueError("图片超过20 MiB")
                                chunks.append(chunk)
                        data = b"".join(chunks)
                        metadata = validate_image(data, mime)
                        if metadata["format"] != "PNG":
                            raise ValueError("当前导入要求PNG图片")
                        target.with_suffix(".part").write_bytes(data)
                        target.with_suffix(".part").replace(target)
                        state["downloaded_this_run"] += 1
                    with (folder / "downloads.jsonl").open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps({"source_record_id": index, "image_id": image["img_id"],
                            "url": url, "path": str(target), "citation": image["desc"], "time": now(), **metadata}, ensure_ascii=False) + "\n")
                    save_json(state_path, state)
                    print(json.dumps({"event": "image_saved", "id": index, "image_id": image["img_id"],
                                      "downloaded_this_run": state["downloaded_this_run"]}), flush=True)
                adapter = LegacyAdapter("jiaguwen", image_folder)
                records = adapter.parse(path)
                result = import_records(engine, PROJECT / "data", source, records, path.read_bytes(), adapter.version, image_folder)
                item.update(status="imported", character=record["charname"], image_count=len(images), **result)
            except (RuntimeError, requests.RequestException, ValueError, OSError) as error:
                item.update(status="blocked" if is_stop_error(error) else "failed",
                            error_type=type(error).__name__, error=str(error))
                if is_stop_error(error):
                    state["status"] = "blocked"
            state["records"].append(item)
            save_json(state_path, state)
            print(json.dumps(item, ensure_ascii=False), flush=True)
            if state["status"] == "blocked":
                break
        if state["status"] == "running":
            state["status"] = "finished"
    except (RuntimeError, requests.RequestException, ValueError, OSError) as error:
        state.update(status="blocked" if is_stop_error(error) else "failed", error_type=type(error).__name__, error=str(error))
    finally:
        if driver:
            driver.quit()
        state["finished_at"] = now()
        state["quality"] = report(engine, PROJECT / "data")
        state["attempted_heads"] = len(state["records"])
        state["not_attempted_ids"] = [i for i in range(args.start, args.end + 1)
                                      if i not in {row["source_record_id"] for row in state["records"]}]
        save_json(state_path, state)
        save_json(PROJECT / "reports" / f"{folder.name}.json", state)
        save_json(PROJECT / "reports/current_quality.json", state["quality"])
        rows = export_rows(engine, include_quarantine=True)
        if args.output:
            state["export"] = write_directory_export(rows, PROJECT / "data", args.output, include_quarantine=True)
            save_json(state_path, state)
            save_json(PROJECT / "reports" / f"{folder.name}.json", state)
        engine.dispose()
    print(json.dumps(state, ensure_ascii=False, indent=2), flush=True)
    return 2 if state["status"] in {"blocked", "failed"} else 0


def main():
    parser = argparse.ArgumentParser(description="有界甲骨文批次试采：逐字检查、逐字事务、单站限速")
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--end", type=int, default=10)
    parser.add_argument("--max-images", type=int, default=100)
    parser.add_argument("--interval", type=float, default=7)
    parser.add_argument("--folder", type=Path, default=PROJECT / "data/batches/jiaguwen_001_010")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.start < 1 or not 0 <= args.end - args.start < 100 or not 1 <= args.max_images <= 100 or args.interval < 5:
        parser.error("范围最多100字头、100张图片，间隔至少5秒")
    if not args.execute:
        print(json.dumps({"status": "dry_run", "range": [args.start, args.end], "max_images": args.max_images}))
        return 0
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
