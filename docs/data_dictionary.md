# 数据字典与导入契约

数据库使用 SQLAlchemy Core，SQLite 首版；Alembic 修订 `0001` 从冻结的 `schema_v1.py` 建表。后续结构变动新增 revision，不修改冻结定义。迁移至 PostgreSQL 尚未验证。

- `source`：来源独立 ID、网址、许可证据、审计状态、测试标志。不同专题库使用不同 ID，防止站内编号串库。
- `character`：内部主键、规范单字、Unicode、种子检查状态。目前 seed_status 仅初始化 not_checked，未实现逐来源/时期缺失状态管理。
- `character_alias`：关系类型和证据；已建表，尚无自动映射。
- `source_record`：来源局部编号、原字头、详情 URL、原始文件 SHA-256/档案路径、解析器版本、导入时间。
- `glyph`：字形实例，时代与书体独立，年代可空，有年代时必须给依据；映射和审阅状态独立。
- `image_asset`：以原图 SHA-256 去重，保存原始字节、格式、尺寸和档案路径，不进行缩放或生成式补全。
- `glyph_image`：字形和图片关联，保存逐图来源 URL、许可及证据。同图跨来源使用时仍保留各自关联。
- `crawl_job`、`review_decision`：已建表；本版尚未实现在线调度及人工审阅修改命令。

## 标准 JSONL

每行是一条来源记录：

```json
{"local_id":"来源内编号","source_url":"https://来源/详情","raw_head":"来源原字头","glyphs":[{"local_key":"来源内图片/字形编号","character":"馬","period":null,"script_style":null,"date_start":null,"date_end":null,"date_basis":null,"citation":"来源实际出处文字","image_path":"相对于 image-root 的本地图片路径","image_url":null,"license_id":null,"license_url":null,"mapping_status":"unverified","review_status":"pending"}]}
```

以上仅为格式示例，不是真实史料。没有统一编码或无法确认的字形，character 填 null，raw_head 保留原文。当前 character 仅接受单个 CJK 统一汉字；兼容字、IVS 和复合字头尚未支持。绝不自动做 NFKC 或繁简合并。

标准导入器要求固定契约；真正的官方导出文件应先按实际格式增加对应 adapter，不能假设官方提供这种 JSONL。

每次输入文件完整存入 raw/imports 并记录哈希。相同 source_id/local_id 和相同输入文件哈希、解析版本视为重复导入；内容变更拒绝覆盖，需要审核。图片/元数据先校验，数据库整批事务写入；失败时内容寻址档案可能保留未引用文件，数据库不会出现半条成功记录。

## 默认导出规则

仅导出非测试、verified、approved、有出处、有详情 URL、有本地原图且逐图许可为 CC0-1.0（附证据 URL）的记录。其他许可尚未配置发布规则，保守留在隔离区。导入配置和这些状态属于操作者的证据声明，软件不会自动证明声明真实。

`--include-quarantine` 可导出待核验记录；测试来源还必须显式加 `--include-test`。查询始终显示各记录的状态。CLI 导出为逐图片扁平记录；同字形多个图片时会有多行。

`report` 中 image_count 为按 SHA-256 去重后的数量，覆盖矩阵表示实际导入分组，不推断缺失时期。空数据集比率使用 null。正式数据与测试数据分别计数。

## 种子表

`data/seeds/characters_100_template.csv` 只有表头，不是已经选好的100字：

```csv
character,list_version,source_url,license_id
```

填写有版本和来源的合法字表后再执行 import-seeds。原始 CSV 会归档，导入不触发联网，也不表示已查询该字。

## 第三方适配器 v2（2026-10-18）

兼容修补后的第三方输出：保留 source_url，raw_head 与 charname 分开，站内编号不会成为规范字头。已导入“一”的3条真实单页结果，映射/审阅仍待确认。原始JSONL附带响应哈希，真实HTTP请求和表单字段另存采集目录 requests.jsonl。主系统逐图许可不从source自动继承。

## 按字头/字形阶段的目录导出

CLI：`hanzi export --format tree --output data/dataset_50 --include-quarantine`。默认 `character` 布局路径为 `<输出目录>/<汉字>/<字形阶段或待分类>/<书体>__<稳定标识>.<原图格式>`，并在汉字目录保存 metadata.jsonl。

`--layout style` 输出字体优先布局：路径为 `<输出目录>/<字形阶段或待分类>/<汉字>/<书体>__<稳定标识>.<原图格式>`，metadata.jsonl 位于 `<字体>/<汉字>/`；manifest 的 layout 为 `style-character-v1`。

- 阶段目录按 script_style 映射：jiaguwen→甲骨文、jinwen→金文、xiaozhuan→小篆、lishu→隶书、kaishu→楷书。其他有名称的书体保留名称，缺少分类用“待分类”。period与具体年代仍原样保留在元数据，不作为目录分类依据。
- 保留同字同一字形阶段的全部实例；图片稳定标识来自source_id、source_record_id、local_key和图片哈希，避免跨来源编号冲突。
- 逐字元数据中 image_path 相对汉字目录，archive_image_path 为数据库内部档案路径，sha256保持原图哈希。
- 已有且完全一致的目录可复用；不同快照必须用新输出目录。失败不发布不完整的新目录。
- 输出为内部待审集时必须显式 include-quarantine；该标志写入manifest，不能当作已审核发布集。
- 未确定字头或没有图片的行仅记跳过数量；不强行归并字头，不创建没有实际图片的阶段目录。

当前布局版本为 character-stage-v1（汉字优先）和 style-character-v1（字体优先）；逐图保留 stage_directory 字段，不再生成 period_directory。历史 character-period-v1 快照不混入新目录。

## 跨来源表单适配器与抽样

`xiaoxue-forms-v1` 接受已核验的金文、小篆、隶变、字形演变结果页。按标准字头匹配expected_character、保留独立source_id/source_record_id；来源编号即使恰好相同也不自动关联。原始归档包包含完整页面/哈希、规范化记录以及sampling声明（available_glyph_count、retained_glyph_count、per_style_limit），不把抽样记作全量。明确零结果仅在页面声明“共搜尋到 0 字”且无 VariantList/StartOrder 时记为 `no_result`；缺少结构、受限页或验证码仍按失败/停止处理。

扩到50字的甲骨文补充包 parser_version 为 `expand50-jiaguwen-v1`，每字最多5张并保留完整页面记录；跨来源补充包为 `expand50-forms-v1`，仍使用同一结果页解析和目录限额。

逐图script_style来自明确字库名称或“說文古文”等出处类型；period仅取来源单元格原始标签，date_basis记录原文，date_start/date_end保持未知。目录新增战国文字、说文古文等分类；kaishu_reference导出为“现代楷书参考”，引用文字明确注明非历史样本。

跨库相同图片仅存一份image_asset，各来源字形/出处关联保留。跨库MVP阶段182条实例文件对应174张不同原图；十字补采后336条关联对应328张不同原图；扩字完成后当前50字头、1023条关联、1015张不同原图。现代楷书参考50条包含在通用glyph_count中，不能把该计数全部解释为历史古文字数量。
