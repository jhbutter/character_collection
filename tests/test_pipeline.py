import json
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import func, insert, select
from typer.testing import CliRunner

from hanzi_evolution import schema_v1 as s
from hanzi_evolution.adapters import GlyphInput, LegacyAdapter, OfficialExportAdapter, RecordInput, SourceInput, inspect_html
from hanzi_evolution.cli import app
from hanzi_evolution.db import open_db
from hanzi_evolution.store import ImportConflict, export_rows, import_records, read_image, report


@pytest.fixture
def setup(tmp_path):
    engine = open_db(tmp_path / "db.sqlite")
    Image.new("RGB", (32, 32), "white").save(tmp_path / "one.png")
    source = SourceInput(id="fixture", name="合成测试", is_test=True)
    record = RecordInput(local_id="1", source_url="https://example.invalid/1", raw_head="馬", glyphs=[
        GlyphInput(local_key="1", character="馬", citation="合成测试非史料", image_path="one.png")])
    yield engine, tmp_path, source, record
    engine.dispose()


def save(setup, records=None, raw=b"synthetic fixture"):
    engine, root, source, record = setup
    return import_records(engine, root, source, records or [record], raw, "test-v1", root)


def test_pipeline_idempotence_and_quarantine(setup):
    engine, root, _, _ = setup
    assert save(setup)["records_imported"] == 1
    assert save(setup)["records_skipped"] == 1
    assert export_rows(engine) == []
    rows = export_rows(engine, include_quarantine=True, include_test=True)
    assert len(rows) == 1
    assert rows[0]["unicode"] == "U+99AC"
    assert (root / rows[0]["raw_path"]).read_bytes() == b"synthetic fixture"
    assert (root / rows[0]["image_path"]).read_bytes() == (root / "one.png").read_bytes()
    assert report(engine, root)["image_validity_rate"] == 1
    assert report(engine, root)["real_glyph_count"] == 0


def test_hash_dedup_preserves_both_glyphs(setup):
    engine, _, _, record = setup
    second = record.model_copy(update={"local_id": "2"})
    save(setup, [record, second])
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(s.image_asset)) == 1
        assert conn.scalar(select(func.count()).select_from(s.glyph_image)) == 2


def test_conflict_rolls_back_whole_batch(setup):
    engine, _, _, record = setup
    save(setup)
    new = record.model_copy(update={"local_id": "2"})
    with pytest.raises(ImportConflict):
        save(setup, [new, record], raw=b"changed input")
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(s.source_record)) == 1


def test_invalid_image_produces_no_records(setup):
    engine, root, _, _ = setup
    (root / "one.png").write_text("<html>Access Restricted</html>")
    with pytest.raises(OSError):
        save(setup)
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(s.source_record)) == 0


def test_image_path_traversal(setup):
    _, root, _, _ = setup
    with pytest.raises(ValueError, match="根目录"):
        read_image(root, "../outside.png")


def test_changed_archive_detected(setup):
    engine, root, _, _ = setup
    save(setup)
    row = export_rows(engine, True, True)[0]
    (root / row["image_path"]).write_bytes(b"broken")
    assert len(report(engine, root)["image_failures"]) == 1


def test_legacy_does_not_turn_numeric_id_into_character(tmp_path):
    path = tmp_path / "legacy.jsonl"
    path.write_text(json.dumps({"id": 1, "charname": "1", "imgList": [
        {"img_id": 0, "desc": "字頭"}, {"img_id": 1, "desc": "出处未核验"}]}))
    records = LegacyAdapter("jiaguwen", tmp_path).parse(path)
    assert records[0].raw_head == "1"
    assert len(records[0].glyphs) == 1
    assert records[0].glyphs[0].character is None
    assert records[0].glyphs[0].period is None
    assert records[0].glyphs[0].mapping_status == "unverified"


def test_source_ids_scope_records(setup):
    engine, root, source, record = setup
    save(setup)
    other = source.model_copy(update={"id": "other_collection"})
    import_records(engine, root, other, [record], b"other", "test-v1", root)
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(s.source_record)) == 2


@pytest.mark.parametrize("html", ["<title>Access Restricted | ASCDC</title>", "<body>服務限制存取</body>"])
def test_restricted_http_200_is_not_empty_result(html):
    assert inspect_html(html)["status"] == "blocked"


@pytest.mark.parametrize("values", [
    {"character": "123"}, {"mapping_status": "verified"},
    {"date_start": -100, "date_end": -200, "date_basis": "test"},
    {"date_start": -100}, {"license_id": "CC0-1.0"},
])
def test_invalid_metadata_rejected(values):
    with pytest.raises(ValueError):
        GlyphInput(local_key="1", **values)


def test_default_export_excludes_test_even_if_approved(setup):
    engine, root, source, record = setup
    g = record.glyphs[0].model_copy(update={"mapping_status": "verified", "review_status": "approved",
        "license_id": "CC0-1.0", "license_url": "https://creativecommons.org/publicdomain/zero/1.0/"})
    record = record.model_copy(update={"glyphs": [g]})
    save(setup, [record])
    assert len(export_rows(engine, include_test=True)) == 1
    assert export_rows(engine) == []


def test_cli_migration_export_and_blocked_network(tmp_path):
    runner = CliRunner()
    db = str(tmp_path / "new.sqlite")
    assert runner.invoke(app, ["init-db", "--db", db]).exit_code == 0
    assert runner.invoke(app, ["init-db", "--db", db]).exit_code == 0
    output = tmp_path / "empty.jsonl"
    result = runner.invoke(app, ["export", "--db", db, "--output", str(output)])
    assert result.exit_code == 0, result.output
    assert output.read_bytes() == b""
    result = runner.invoke(app, ["crawl", "--execute"])
    assert result.exit_code == 2
    assert '"network_requests": 0' in result.output


def test_legacy_preserves_explicit_source_and_numeric_raw_head(tmp_path):
    path = tmp_path / "legacy.jsonl"
    path.write_text(json.dumps({"id": 1, "charname": "一", "raw_head": "1",
        "source_url": "https://xiaoxue.iis.sinica.edu.tw/jiaguwen/?ZiOrder=1",
        "imgList": [{"img_id": 2, "desc": "出处"}]}))
    record = LegacyAdapter("jiaguwen", tmp_path).parse(path)[0]
    assert record.raw_head == "1"
    assert record.glyphs[0].character == "一"
    assert record.source_url.endswith("ZiOrder=1")
    assert record.glyphs[0].mapping_status == "unverified"


def test_directory_export_groups_characters_and_stages(setup):
    from hanzi_evolution.store import write_directory_export
    engine, root, _, record = setup
    unknown = record.model_copy(update={"glyphs": [record.glyphs[0].model_copy(update={"script_style": "jiaguwen"})]})
    known = record.model_copy(update={"local_id": "2", "glyphs": [record.glyphs[0].model_copy(update={"period": "商代", "script_style": "jiaguwen"})]})
    other = record.model_copy(update={"local_id": "3", "glyphs": [record.glyphs[0].model_copy(update={"character": "一", "period": "商代", "script_style": "jinwen"})]})
    save(setup, [unknown, known, other])
    rows = export_rows(engine, True, True)
    output = root / "dataset"
    result = write_directory_export(rows, root, output, True, True)
    assert result["character_count"] == 2
    assert result["image_file_count"] == 3
    assert len(list((output / "馬/甲骨文").glob("甲骨文__*.png"))) == 2
    assert not (output / "馬/商代").exists()
    assert len(list((output / "一/金文").glob("*.png"))) == 1
    metadata = [json.loads(line) for line in (output / "馬/metadata.jsonl").read_text().splitlines()]
    assert {row["period"] for row in metadata} == {None, "商代"}
    assert {row["stage_directory"] for row in metadata} == {"甲骨文"}
    for path in output.rglob("*.png"):
        assert path.read_bytes() == (root / "one.png").read_bytes()
    for row in metadata:
        assert (output / "馬" / row["image_path"]).is_file()
        assert row["citation"] == "合成测试非史料"
    assert write_directory_export(rows, root, output, True, True)["reused"] is True


def test_directory_export_does_not_overwrite_other_files(setup):
    from hanzi_evolution.store import write_directory_export
    engine, root, _, _ = setup
    save(setup)
    output = root / "existing"
    output.mkdir()
    note = output / "note.txt"
    note.write_text("user notes")
    with pytest.raises(ValueError, match="目标目录"):
        write_directory_export(export_rows(engine, True, True), root, output)
    assert note.read_text() == "user notes"
    assert list(output.iterdir()) == [note]


def test_directory_export_rejects_damaged_images_before_publish(setup):
    from hanzi_evolution.store import write_directory_export
    engine, root, _, _ = setup
    save(setup)
    rows = export_rows(engine, True, True)
    rows[0]["sha256"] = "0" * 64
    output = root / "dataset"
    with pytest.raises(ValueError, match="哈希"):
        write_directory_export(rows, root, output)
    assert not output.exists()


def test_directory_export_sanitizes_stage_paths(setup):
    from hanzi_evolution.store import write_directory_export
    engine, root, _, _ = setup
    save(setup)
    rows = export_rows(engine, True, True)
    rows[0]["script_style"] = "../../outside"
    output = root / "dataset"
    write_directory_export(rows, root, output)
    files = list(output.rglob("*.png"))
    assert len(files) == 1
    assert files[0].resolve().is_relative_to(output.resolve())
    assert not (root / "outside").exists()


def test_cli_directory_export_keeps_test_opt_in(setup):
    engine, root, _, _ = setup
    save(setup)
    runner = CliRunner()
    output = root / "dataset"
    result = runner.invoke(app, ["export", "--format", "tree", "--db", str(root / "db.sqlite"),
        "--root", str(root), "--output", str(output), "--include-quarantine", "--include-test"])
    assert result.exit_code == 0, result.output
    assert len(list((output / "馬/待分类").glob("*.png"))) == 1
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["includes_quarantine"] is True
    assert manifest["includes_test"] is True


def test_directory_export_stage_does_not_require_dating(setup):
    from hanzi_evolution.store import write_directory_export
    engine, root, _, record = setup
    styles = {"jiaguwen": "甲骨文", "jinwen": "金文", "xiaozhuan": "小篆", "lishu": "隶书", "kaishu": "楷书"}
    records = [record.model_copy(update={"local_id": str(index), "glyphs": [
        record.glyphs[0].model_copy(update={"script_style": style})]})
        for index, style in enumerate(styles, start=1)]
    save(setup, records)
    output = root / "dataset"
    write_directory_export(export_rows(engine, True, True), root, output, True, True)
    assert {path.name for path in (output / "馬").iterdir() if path.is_dir()} == set(styles.values())
    metadata = [json.loads(line) for line in (output / "馬/metadata.jsonl").read_text().splitlines()]
    assert all(row["period"] is None and row["date_start"] is None for row in metadata)
    assert json.loads((output / "manifest.json").read_text())["layout"] == "character-stage-v1"


def test_directory_export_limits_each_character_style_across_sources(setup):
    from hanzi_evolution.store import write_directory_export
    engine, root, _, _ = setup
    save(setup)
    template = export_rows(engine, True, True)[0]
    rows = []
    for character, style, count in [("馬", "jiaguwen", 8), ("馬", "jinwen", 7), ("一", "jiaguwen", 6)]:
        for index in range(count):
            rows.append({**template, "glyph_id": len(rows) + 1, "character": character,
                "script_style": style, "source_id": f"source{index % 2}",
                "source_record_id": str(index), "period": f"时期{index}"})
    output = root / "limited"
    result = write_directory_export(list(reversed(rows)), root, output, True, True)
    assert result["image_file_count"] == 15
    for character, stage in [("馬", "甲骨文"), ("馬", "金文"), ("一", "甲骨文")]:
        assert len(list((output / character / stage).glob("*.png"))) == 5
    metadata = [json.loads(line) for line in (output / "馬/metadata.jsonl").read_text().splitlines()]
    assert {row["glyph_id"] for row in metadata} == {1, 2, 3, 4, 5, 9, 10, 11, 12, 13}
    assert all((output / "馬" / row["image_path"]).is_file() for row in metadata)
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["max_images_per_character_style"] == 5
    assert manifest["skipped_style_limit_rows"] == 6
    assert write_directory_export(rows, root, output, True, True)["reused"] is True
