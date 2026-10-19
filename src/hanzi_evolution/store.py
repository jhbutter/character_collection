import csv
import hashlib
import json
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from PIL import Image
from sqlalchemy import func, insert, select

from . import schema_v1 as s
from .adapters import RecordInput, SourceInput


class ImportConflict(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def archive(root: Path, data: bytes, directory: str, suffix: str):
    digest = hashlib.sha256(data).hexdigest()
    relative = Path(directory) / digest[:2] / f"{digest}{suffix}"
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() != data:
        raise ValueError("内容寻址档案损坏，请先恢复原文件")
    if not target.exists():
        target.write_bytes(data)
    return digest, relative.as_posix()


def read_image(image_root: Path, relative: str):
    path = (image_root / relative).resolve()
    if not path.is_relative_to(image_root.resolve()):
        raise ValueError("图片路径越出导入根目录")
    if path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("图片超过 20 MiB")
    data = path.read_bytes()
    with Image.open(BytesIO(data)) as image:
        if image.format not in {"PNG", "JPEG", "GIF", "TIFF", "WEBP"}:
            raise ValueError("不支持的图片格式")
        if image.width * image.height > 40_000_000:
            raise ValueError("图片像素超过上限")
        fmt, width, height = image.format, image.width, image.height
        image.verify()
    with Image.open(BytesIO(data)) as image:
        image.load()
    extensions = {"PNG": ".png", "JPEG": ".jpg", "GIF": ".gif", "TIFF": ".tif", "WEBP": ".webp"}
    return data, Image.MIME[fmt], width, height, extensions[fmt]


def import_records(engine, root: Path, source: SourceInput, records: list[RecordInput],
                   raw: bytes, parser_version: str, image_root: Path):
    prepared = {}
    for record in records:
        for glyph in record.glyphs:
            if glyph.image_path:
                prepared[(record.local_id, glyph.local_key)] = read_image(image_root, glyph.image_path)
    if len({r.local_id for r in records}) != len(records):
        raise ValueError("输入文件中 local_id 重复")
    raw_hash, raw_path = archive(root, raw, "raw/imports", ".jsonl")
    result = {"records_imported": 0, "records_skipped": 0, "glyphs_imported": 0}
    with engine.begin() as conn:
        existing = conn.execute(select(s.source).where(s.source.c.id == source.id)).mappings().first()
        source_values = source.model_dump()
        source_values["is_test"] = int(source.is_test)
        if existing and dict(existing) != source_values:
            raise ImportConflict("来源配置发生变化，需审核后迁移；请勿覆盖既有来源许可或测试标记")
        if not existing:
            conn.execute(insert(s.source).values(**source_values))
        for record in records:
            previous = conn.execute(select(s.source_record).where(
                s.source_record.c.source_id == source.id,
                s.source_record.c.local_id == record.local_id)).mappings().first()
            if previous:
                if previous["raw_sha256"] != raw_hash or previous["parser_version"] != parser_version:
                    raise ImportConflict(f"记录 {record.local_id} 已存在但输入或解析版本不同，需人工审核")
                result["records_skipped"] += 1
                continue
            record_id = conn.execute(insert(s.source_record).values(source_id=source.id,
                local_id=record.local_id, source_url=record.source_url, raw_head=record.raw_head,
                raw_sha256=raw_hash, raw_path=raw_path, parser_version=parser_version,
                imported_at=now())).inserted_primary_key[0]
            for glyph in record.glyphs:
                character_id = None
                if glyph.character:
                    character_id = conn.scalar(select(s.character.c.id).where(s.character.c.label == glyph.character))
                    if character_id is None:
                        character_id = conn.execute(insert(s.character).values(label=glyph.character,
                            unicode=f"U+{ord(glyph.character):04X}", seed_status="not_checked")).inserted_primary_key[0]
                glyph_id = conn.execute(insert(s.glyph).values(record_id=record_id,
                    character_id=character_id,
                    **glyph.model_dump(exclude={"character", "image_path", "image_url", "license_id", "license_url"}))).inserted_primary_key[0]
                image = prepared.get((record.local_id, glyph.local_key))
                if image:
                    data, mime, width, height, suffix = image
                    digest, path = archive(root, data, "images/original", suffix)
                    if not conn.scalar(select(s.image_asset.c.sha256).where(s.image_asset.c.sha256 == digest)):
                        conn.execute(insert(s.image_asset).values(sha256=digest, path=path, mime=mime, width=width, height=height))
                    conn.execute(insert(s.glyph_image).values(glyph_id=glyph_id, asset_sha256=digest,
                        original_url=glyph.image_url, license_id=glyph.license_id,
                        license_url=glyph.license_url, imported_at=now()))
                result["glyphs_imported"] += 1
            result["records_imported"] += 1
    return result


def export_rows(engine, include_quarantine=False, include_test=False):
    statement = select(s.glyph.c.id.label("glyph_id"), s.character.c.label.label("character"),
        s.character.c.unicode, s.source.c.id.label("source_id"),
        s.source.c.name.label("source_name"), s.source.c.is_test,
        s.source_record.c.local_id.label("source_record_id"), s.source_record.c.source_url,
        s.source_record.c.raw_head, s.source_record.c.raw_sha256, s.source_record.c.raw_path,
        s.source_record.c.parser_version, s.glyph.c.local_key,
        s.glyph.c.period, s.glyph.c.script_style, s.glyph.c.date_start, s.glyph.c.date_end,
        s.glyph.c.date_basis, s.glyph.c.citation, s.glyph.c.mapping_status, s.glyph.c.review_status,
        s.image_asset.c.path.label("image_path"), s.image_asset.c.sha256,
        s.glyph_image.c.original_url, s.glyph_image.c.license_id, s.glyph_image.c.license_url
    ).select_from(s.glyph.join(s.source_record).join(s.source)
        .outerjoin(s.character).outerjoin(s.glyph_image).outerjoin(s.image_asset)).order_by(s.glyph.c.id)
    if not include_test:
        statement = statement.where(s.source.c.is_test == 0)
    if not include_quarantine:
        statement = statement.where(s.glyph.c.mapping_status == "verified",
            s.glyph.c.review_status == "approved", s.glyph.c.citation.is_not(None),
            s.source_record.c.source_url.is_not(None), s.image_asset.c.sha256.is_not(None),
            s.glyph_image.c.license_id == "CC0-1.0", s.glyph_image.c.license_url.is_not(None))
    with engine.connect() as conn:
        return [dict(row) for row in conn.execute(statement).mappings()]


def report(engine, root: Path):
    rows = export_rows(engine, include_quarantine=True, include_test=True)
    real = [row for row in rows if not row["is_test"]]
    eligible = export_rows(engine)
    with engine.connect() as conn:
        seed_count = conn.scalar(select(func.count()).select_from(s.character))
        assets = conn.execute(select(s.image_asset)).mappings().all()
    valid = 0
    failures = []
    for asset in assets:
        try:
            data, _, _, _, _ = read_image(root, asset["path"])
            if hashlib.sha256(data).hexdigest() != asset["sha256"]:
                raise ValueError("SHA-256 不匹配")
            valid += 1
        except (OSError, ValueError, Image.DecompressionBombError) as error:
            failures.append({"path": asset["path"], "error": str(error)})
    matrix = {}
    for row in real:
        key = f"{row['period'] or 'unknown'} / {row['script_style'] or 'unknown'}"
        matrix[key] = matrix.get(key, 0) + 1
    traceable = sum(bool(r["source_url"] and r["source_record_id"]) for r in real)
    return {"character_count_including_test": seed_count,
        "real_glyph_count": len({r["glyph_id"] for r in real}),
        "real_with_image_character_count": len({r["character"] for r in real if r["character"] and r["sha256"]}),
        "real_image_count": len({r["sha256"] for r in real if r["sha256"]}),
        "test_glyph_count": len({r["glyph_id"] for r in rows if r["is_test"]}),
        "publishable_glyph_count": len({r["glyph_id"] for r in eligible}),
        "unique_image_count_including_test": len(assets),
        "image_validity_rate": valid / len(assets) if assets else None,
        "source_traceability_rate": traceable / len(real) if real else None,
        "coverage": matrix, "image_failures": failures}


def write_export(rows, output: Path, fmt: str):
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        if fmt == "jsonl":
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        else:
            fields = list(rows[0]) if rows else ["glyph_id", "character", "source_id", "source_record_id", "image_path", "sha256"]
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)


def write_directory_export(rows, root: Path, output: Path, include_quarantine=False, include_test=False,
                           layout="character"):
    import re
    import shutil
    import tempfile
    import unicodedata

    if layout not in {"character", "style"}:
        raise ValueError("导出布局只能为 character 或 style")
    root, output = root.resolve(), output.absolute()
    resolved_output = output.resolve()
    if resolved_output == root or root.is_relative_to(resolved_output) or output.is_symlink():
        raise ValueError("导出目录不能覆盖原始数据根目录或使用符号链接")

    def component(value):
        value = re.sub(r'[%/\\:\x00-\x1f<>"|?*]',
                       lambda match: "".join(f"%{byte:02X}" for byte in match[0].encode()), value)
        if value in {".", ".."}:
            value = value.replace(".", "%2E")
        return value

    stages = {"jiaguwen": "甲骨文", "jinwen": "金文", "xiaozhuan": "小篆",
              "zhuanshu": "篆书", "lishu": "隶书", "kaishu": "楷书",
              "xingshu": "行书", "caoshu": "草书", "chuwenzi": "楚系简帛文字",
              "qinwenzi": "秦系简牍文字", "chuanchao": "传抄古文字",
              "zhanguowenzi": "战国文字", "shuowen_guwen": "说文古文",
              "shuowen_zhouwen": "说文籀文", "kaishu_reference": "现代楷书参考"}
    groups, assets = {}, {}
    skipped_unmapped = skipped_missing_image = skipped_style_limit = 0
    stage_counts = {}
    for row in sorted(rows, key=lambda row: (row["glyph_id"], row["sha256"] or "")):
        label = row["character"]
        if not label or len(label) != 1 or not unicodedata.name(label, "").startswith("CJK UNIFIED IDEOGRAPH"):
            skipped_unmapped += 1
            continue
        if not row["image_path"] or not row["sha256"]:
            skipped_missing_image += 1
            continue
        script = row["script_style"]
        stage = component(stages.get(script, script or "待分类"))
        if not stage or len(stage.encode("utf-8")) > 180:
            raise ValueError("字形阶段目录名为空或过长")
        key = (label, stage)
        if stage_counts.get(key, 0) >= 5:
            skipped_style_limit += 1
            continue
        data, _, _, _, suffix = read_image(root, row["image_path"])
        if hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise ValueError(f"原图哈希不匹配：{row['image_path']}")
        stage_counts[key] = stage_counts.get(key, 0) + 1
        identity = json.dumps([row["source_id"], row["source_record_id"], row["local_key"], row["sha256"]], ensure_ascii=False)
        token = hashlib.sha256(identity.encode()).hexdigest()[:24]
        filename = f"{stage[:20]}__{token}{suffix}"
        if layout == "character":
            relative = Path(stage) / filename
            group_key = label
            destination = (Path(label) / relative).as_posix()
            image_path = relative.as_posix()
        else:
            relative = Path(label) / filename
            group_key = (stage, label)
            destination = (Path(stage) / relative).as_posix()
            image_path = filename
        exported = {**row, "archive_image_path": row["image_path"],
                    "image_path": image_path, "stage_directory": stage}
        groups.setdefault(group_key, []).append(exported)
        if destination in assets and assets[destination][1] != row["sha256"]:
            raise ValueError("导出文件名冲突")
        assets[destination] = (root / row["image_path"], row["sha256"])

    files = {path: digest for path, (_, digest) in assets.items()}
    metadata_files = {}
    for key, records in sorted(groups.items()):
        records.sort(key=lambda row: (row["image_path"], row["glyph_id"]))
        payload = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in records).encode()
        if layout == "character":
            path = f"{key}/metadata.jsonl"
        else:
            stage, label = key
            path = f"{stage}/{label}/metadata.jsonl"
        metadata_files[path] = payload
        files[path] = hashlib.sha256(payload).hexdigest()
    all_records = [row for records in groups.values() for row in records]
    character_count = len({row["character"] for row in all_records})
    style_count = len({row["stage_directory"] for row in all_records})
    stage_policy = "按script_style分为甲骨文、金文、小篆等字形阶段；缺少分类用待分类，具体断代保留在元数据"
    manifest = {"layout": "character-stage-v1" if layout == "character" else "style-character-v1",
                "includes_quarantine": include_quarantine,
                "includes_test": include_test, "character_count": character_count,
                "glyph_count": len({row["glyph_id"] for row in all_records}),
                "image_file_count": len(assets), "skipped_unmapped_rows": skipped_unmapped,
                "skipped_missing_image_rows": skipped_missing_image,
                "max_images_per_character_style": 5,
                "selection_order": "glyph_id ascending",
                "skipped_style_limit_rows": skipped_style_limit,
                "stage_policy": stage_policy,
                "files": dict(sorted(files.items()))}
    if layout == "style":
        manifest.update({"grouping": "style-first", "style_count": style_count,
                         "group_count": len(groups),
                         "stage_policy": stage_policy + "；目录按字体优先，字体/汉字/图片"})
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    if output.exists():
        if not output.is_dir():
            raise ValueError("导出位置不是目录")
        expected = {**files, "manifest.json": hashlib.sha256(manifest_bytes).hexdigest()}
        actual = {path.relative_to(output).as_posix(): path for path in output.rglob("*") if path.is_file()}
        if set(actual) != set(expected) or any(
            path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected[name]
            for name, path in actual.items()
        ):
            raise ValueError("目标目录已存在且内容不同，请使用新的导出目录，避免混入旧数据或覆盖文件")
        return {**{key: manifest[key] for key in ("character_count", "glyph_count", "image_file_count")},
                "layout": manifest["layout"], "output": str(output), "reused": True}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".hanzi-export-", dir=output.parent) as temporary:
        stage = Path(temporary) / "dataset"
        stage.mkdir()
        for relative, (source_path, digest) in assets.items():
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, target)
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise ValueError("复制后图片哈希不匹配")
        for relative, payload in metadata_files.items():
            (stage / relative).write_bytes(payload)
        (stage / "manifest.json").write_bytes(manifest_bytes)
        stage.rename(output)
    return {**{key: manifest[key] for key in ("character_count", "glyph_count", "image_file_count")},
            "layout": manifest["layout"], "output": str(output), "reused": False}
