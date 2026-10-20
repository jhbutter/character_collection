import csv
import json
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import insert, select

from . import schema_v1 as s
from .adapters import GlyphInput, LegacyAdapter, OfficialExportAdapter, SourceInput, inspect_html
from .db import open_db
from .store import import_records, report as make_report, export_rows, write_export, write_directory_export

app = typer.Typer(help="汉字历时字形资料库：离线导入、溯源、查询与导出", no_args_is_help=True)
DB = Annotated[Path, typer.Option(help="SQLite 数据库")]
ROOT = Annotated[Path, typer.Option(help="原始输入和图片档案根目录")]


def emit(value):
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2))


@app.command("init-db")
def init_db(db: DB = Path("data/hanzi.sqlite")):
    open_db(db).dispose()
    emit({"database": str(db.resolve()), "schema_version": "0001"})


@app.command("inspect-page")
def inspect_page(path: Path):
    result = inspect_html(path.read_text(encoding="utf-8"))
    emit(result)
    if result["status"] == "blocked":
        raise typer.Exit(2)


@app.command("import-official-export")
def import_official_export(path: Path, source_config: Annotated[Path, typer.Option()],
                           image_root: Annotated[Path, typer.Option()] = Path("."),
                           db: DB = Path("data/hanzi.sqlite"), root: ROOT = Path("data")):
    run_import(path, source_config, OfficialExportAdapter(), image_root, db, root)


@app.command("import-legacy")
def import_legacy(path: Path, source_config: Annotated[Path, typer.Option()],
                  collection: Annotated[str, typer.Option()], image_root: Annotated[Path, typer.Option()],
                  db: DB = Path("data/hanzi.sqlite"), root: ROOT = Path("data")):
    try:
        adapter = LegacyAdapter(collection, image_root)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    run_import(path, source_config, adapter, image_root, db, root)


def run_import(path, source_config, adapter, image_root, db, root):
    try:
        source = SourceInput.model_validate_json(source_config.read_text(encoding="utf-8"))
        records = adapter.parse(path)
        engine = open_db(db)
        try:
            emit(import_records(engine, root, source, records, path.read_bytes(), adapter.version, image_root))
        finally:
            engine.dispose()
    except (ValueError, OSError) as error:
        raise typer.BadParameter(str(error)) from error


@app.command("import-seeds")
def import_seeds(path: Path, db: DB = Path("data/hanzi.sqlite")):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        GlyphInput(local_key="seed", character=row["character"])
        if not row.get("list_version") or not row.get("source_url") or not row.get("license_id"):
            raise typer.BadParameter("种子表需要 character,list_version,source_url,license_id")
    engine = open_db(db)
    count = 0
    with engine.begin() as conn:
        for row in rows:
            label = row["character"]
            if not conn.scalar(select(s.character.c.id).where(s.character.c.label == label)):
                conn.execute(insert(s.character).values(label=label, unicode=f"U+{ord(label):04X}", seed_status="not_checked"))
                count += 1
    from .store import archive
    archive(db.resolve().parent, path.read_bytes(), "raw/seeds", ".csv")
    emit({"seeds_added": count, "rows": len(rows), "status": "not_checked"})


@app.command()
def lookup(character: Annotated[str, typer.Option()], db: DB = Path("data/hanzi.sqlite"),
           include_test: Annotated[bool, typer.Option()] = False):
    rows = export_rows(open_db(db), include_quarantine=True, include_test=include_test)
    emit([row for row in rows if row["character"] == character or row["unicode"] == character])


@app.command()
def export(output: Annotated[Path, typer.Option()], db: DB = Path("data/hanzi.sqlite"),
           format: Annotated[str, typer.Option()] = "jsonl", root: ROOT = Path("data"),
           layout: Annotated[str, typer.Option(help="tree 布局：character 或 style")] = "character",
           include_quarantine: Annotated[bool, typer.Option()] = False,
           include_test: Annotated[bool, typer.Option()] = False):
    if format not in {"csv", "jsonl", "tree"}:
        raise typer.BadParameter("format 只能为 csv、jsonl 或 tree")
    if layout not in {"character", "style"}:
        raise typer.BadParameter("layout 只能为 character 或 style")
    if format != "tree" and layout != "character":
        raise typer.BadParameter("layout 只用于 tree 导出")
    if output.resolve() == db.resolve():
        raise typer.BadParameter("输出路径不能覆盖数据库")
    rows = export_rows(open_db(db), include_quarantine, include_test)
    if format == "tree":
        try:
            emit(write_directory_export(rows, root, output, include_quarantine, include_test,
                                        layout=layout))
        except (ValueError, OSError) as error:
            raise typer.BadParameter(str(error)) from error
    else:
        write_export(rows, output, format)
        emit({"exported_rows": len(rows), "includes_quarantine": include_quarantine, "includes_test": include_test})


@app.command()
def report(db: DB = Path("data/hanzi.sqlite"), root: ROOT = Path("data"),
           output: Annotated[Path | None, typer.Option()] = None):
    result = make_report(open_db(db), root)
    if output:
        if output.resolve() == db.resolve():
            raise typer.BadParameter("报告路径不能覆盖数据库")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    emit(result)


@app.command("validate-images")
def validate_images(db: DB = Path("data/hanzi.sqlite"), root: ROOT = Path("data")):
    result = make_report(open_db(db), root)
    emit({key: result[key] for key in ("unique_image_count_including_test", "image_validity_rate", "image_failures")})
    if result["image_failures"]:
        raise typer.Exit(1)


@app.command("collect-expand")
@app.command("collect-expand50")
def collect_expand50(
    execute: Annotated[bool, typer.Option(help="联网执行；默认 dry-run")] = False,
    start_id: Annotated[int, typer.Option(min=1)] = 11,
    end_id: Annotated[int, typer.Option()] = 60,
    target: Annotated[int, typer.Option(min=1, max=100)] = 50,
    max_images: Annotated[int, typer.Option(min=1, max=100)] = 100,
    interval: Annotated[float, typer.Option()] = 7,
    folder: Annotated[Path, typer.Option()] = Path("data/batches/expand_50"),
    output: Annotated[Path, typer.Option()] = Path("data/dataset_50"),
    modern_reference: Annotated[bool, typer.Option("--modern-reference/--no-modern-reference")] = True,
    export: Annotated[bool, typer.Option("--export/--no-export")] = True,
    new_only: Annotated[bool, typer.Option("--new-only/--all-characters")] = False,
):
    """按甲骨文编号扩采字头，再采金文、小篆、隶变及字形演变；默认 dry-run。"""
    if start_id < 1 or not 0 <= end_id - start_id < 100:
        raise typer.BadParameter("编号范围必须从 1 开始且最多 100 个编号")
    if interval < 5:
        raise typer.BadParameter("间隔至少 5 秒")
    if not execute:
        emit({"status": "dry_run", "range": [start_id, end_id], "target": target,
              "oracle_limit": 5, "max_images": max_images, "network_requests": 0,
              "output": str(output.resolve())})
        return
    from types import SimpleNamespace
    from .collection.expand import run
    args = SimpleNamespace(folder=folder, start_id=start_id, end_id=end_id,
                           target=target, max_images=max_images, interval=interval,
                           output=output, no_modern_reference=not modern_reference,
                           no_export=not export, new_only=new_only)
    raise typer.Exit(run(args))


@app.command()
def crawl(source: Annotated[str, typer.Option()] = "xiaoxue",
          limit: Annotated[int, typer.Option(min=1, max=100)] = 1,
          execute: Annotated[bool, typer.Option()] = False,
          dry_run: Annotated[bool, typer.Option()] = True):
    emit({"source": source, "limit": limit, "network_requests": 0,
          "status": "blocked" if execute else "dry_run",
          "reason": "主系统尚未接入第三方采集器；已验证的单条调试入口见 README，批量调度未启用"})
    if execute:
        raise typer.Exit(2)


if __name__ == "__main__":
    app()
