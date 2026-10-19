from sqlalchemy import Column, ForeignKey, Integer, MetaData, String, Table, Text, UniqueConstraint

metadata = MetaData()

source = Table("source", metadata,
    Column("id", String, primary_key=True), Column("name", Text, nullable=False),
    Column("url", Text), Column("license_id", String), Column("license_url", Text),
    Column("audit_status", String, nullable=False), Column("is_test", Integer, nullable=False))
character = Table("character", metadata,
    Column("id", Integer, primary_key=True), Column("label", Text, nullable=False, unique=True),
    Column("unicode", String), Column("seed_status", String, nullable=False, default="not_checked"))
character_alias = Table("character_alias", metadata,
    Column("id", Integer, primary_key=True), Column("character_id", ForeignKey("character.id"), nullable=False),
    Column("alias", Text, nullable=False), Column("relation_type", String, nullable=False),
    Column("evidence", Text, nullable=False))
source_record = Table("source_record", metadata,
    Column("id", Integer, primary_key=True), Column("source_id", ForeignKey("source.id"), nullable=False),
    Column("local_id", String, nullable=False), Column("source_url", Text), Column("raw_head", Text),
    Column("raw_sha256", String, nullable=False), Column("raw_path", Text, nullable=False),
    Column("parser_version", String, nullable=False), Column("imported_at", String, nullable=False),
    UniqueConstraint("source_id", "local_id"))
glyph = Table("glyph", metadata,
    Column("id", Integer, primary_key=True), Column("record_id", ForeignKey("source_record.id"), nullable=False),
    Column("local_key", String, nullable=False), Column("character_id", ForeignKey("character.id")),
    Column("period", String), Column("script_style", String), Column("date_start", Integer),
    Column("date_end", Integer), Column("date_basis", Text), Column("citation", Text),
    Column("mapping_status", String, nullable=False), Column("review_status", String, nullable=False),
    UniqueConstraint("record_id", "local_key"))
image_asset = Table("image_asset", metadata,
    Column("sha256", String, primary_key=True), Column("path", Text, nullable=False),
    Column("mime", String, nullable=False), Column("width", Integer, nullable=False),
    Column("height", Integer, nullable=False))
glyph_image = Table("glyph_image", metadata,
    Column("glyph_id", ForeignKey("glyph.id"), primary_key=True),
    Column("asset_sha256", ForeignKey("image_asset.sha256"), primary_key=True),
    Column("original_url", Text), Column("license_id", String), Column("license_url", Text),
    Column("imported_at", String, nullable=False))
crawl_job = Table("crawl_job", metadata,
    Column("id", Integer, primary_key=True), Column("source_id", ForeignKey("source.id"), nullable=False),
    Column("url", Text, nullable=False), Column("status", String, nullable=False),
    Column("retry_count", Integer, nullable=False, default=0), Column("last_error", Text),
    Column("next_allowed_at", String))
review_decision = Table("review_decision", metadata,
    Column("id", Integer, primary_key=True), Column("glyph_id", ForeignKey("glyph.id"), nullable=False),
    Column("before_json", Text, nullable=False), Column("after_json", Text, nullable=False),
    Column("evidence", Text, nullable=False), Column("reviewed_at", String, nullable=False))
