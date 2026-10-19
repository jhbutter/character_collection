import json
import unicodedata
from pathlib import Path
from typing import Literal, Protocol

from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class GlyphInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    local_key: str
    character: str | None = None
    period: str | None = None
    script_style: str | None = None
    date_start: int | None = None
    date_end: int | None = None
    date_basis: str | None = None
    citation: str | None = None
    image_path: str | None = None
    image_url: str | None = None
    license_id: str | None = None
    license_url: str | None = None
    mapping_status: Literal["unverified", "verified"] = "unverified"
    review_status: Literal["pending", "approved", "rejected"] = "pending"

    @field_validator("character")
    @classmethod
    def validate_character(cls, value):
        if value is not None:
            if len(value) != 1 or not unicodedata.name(value, "").startswith("CJK UNIFIED IDEOGRAPH"):
                raise ValueError("规范字头须为单个已编码 CJK 汉字；无编码字形请留空，并保留 raw_head")
        return value

    @model_validator(mode="after")
    def check_mapping_and_dates(self):
        if self.mapping_status == "verified" and self.character is None:
            raise ValueError("verified 映射需要明确汉字")
        if self.date_start is not None and self.date_end is not None and self.date_start > self.date_end:
            raise ValueError("date_start 不能晚于 date_end")
        if (self.date_start is not None or self.date_end is not None) and not self.date_basis:
            raise ValueError("年代需要 date_basis")
        if self.license_id and not self.license_url:
            raise ValueError("图片许可需要证据 URL")
        return self


class RecordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    local_id: str
    source_url: str | None = None
    raw_head: str | None = None
    glyphs: list[GlyphInput]

    @model_validator(mode="after")
    def unique_keys(self):
        keys = [g.local_key for g in self.glyphs]
        if len(keys) != len(set(keys)):
            raise ValueError("记录中的 local_key 不能重复")
        return self


class SourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    url: str | None = None
    license_id: str | None = None
    license_url: str | None = None
    audit_status: Literal["pending", "blocked", "import_only", "approved"] = "pending"
    is_test: bool = False

    @model_validator(mode="after")
    def check_license(self):
        if self.license_id and not self.license_url:
            raise ValueError("来源许可需要证据 URL")
        return self


class SourceAdapter(Protocol):
    version: str

    def parse(self, path: Path) -> list[RecordInput]: ...


class OfficialExportAdapter:
    version = "official-jsonl-v1"

    def parse(self, path: Path) -> list[RecordInput]:
        return [RecordInput.model_validate(json.loads(line))
                for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class LegacyAdapter:
    version = "xiaoxue-legacy-v2"

    def __init__(self, collection: str, image_root: Path):
        if collection not in {"jiaguwen", "jinwen", "xiaozhuan"}:
            raise ValueError("仅支持明确指定的 jiaguwen / jinwen / xiaozhuan 分类")
        self.collection = collection
        self.image_root = image_root

    def parse(self, path: Path) -> list[RecordInput]:
        records = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            obj = json.loads(line)
            local_id = str(obj["id"])
            if not local_id.isdecimal():
                raise ValueError("第三方记录编号必须为非负整数")
            charname = str(obj.get("charname", "")) or None
            raw_head = str(obj.get("raw_head", obj.get("charname", ""))) or None
            head = charname if charname and len(charname) == 1 and unicodedata.name(charname, "").startswith("CJK UNIFIED IDEOGRAPH") else None
            glyphs = []
            for item in obj["imgList"]:
                if item.get("desc", "").strip() in {"字頭", "楷書字型"}:
                    continue
                key = str(item["img_id"])
                if not key.isdecimal():
                    raise ValueError("图片编号必须为非负整数")
                image_path = f"{local_id}_{key}.png"
                glyphs.append(GlyphInput(local_key=key, character=head,
                    script_style=self.collection, citation=item.get("desc") or None,
                    image_url=item.get("img_url"),
                    image_path=image_path if (self.image_root / image_path).is_file() else None))
            records.append(RecordInput(local_id=local_id, source_url=obj.get("source_url"),
                                       raw_head=raw_head, glyphs=glyphs))
        return records


def inspect_html(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    text = soup.get_text(" ", strip=True)
    if any(token in title + " " + text for token in
           ("Access Restricted", "服務限制存取", "服务限制访问", "Access Denied")):
        return {"status": "blocked", "title": title, "reason": "访问受限页面，不能作为空查询结果"}
    return {"status": "unverified", "title": title,
            "reason": "仅完成离线检查；真实页面字段和分页尚未核验，未启用在线解析器"}
