# 汉字历时字形图像数据库：项目计划与 Codex 实施指南

> 本文档既是项目说明书，也是提供给 Codex 的实施任务规范。当前位于 `docs/plan.md`，让 Codex 按阶段执行并提交可运行代码、测试、文档和样本数据。
> 状态：规划阶段；以下 URL、网页参数、字段及第三方爬虫兼容性均须实测，不得视为已验证 API。

## 1. 项目愿景

建设一套**可追溯、可扩展、可复现**的汉字历时字形图像数据库，以约 **3,000–5,000 个汉字字头**为目标，收集其在甲骨文、金文、战国文字、篆书、隶书、楷书等时期/书体中的真实字形图片及元数据。允许某个字缺少部分时期的资料；同一字、同一时期可以有多张不同出处的字形。

**关键原则：不臆造演化链。** “时期”与“书体”是不同的分类维度，且年代可能交叠。要记录证据而不是将全部字形强行排列为单线进化顺序。

### 1.1 预期成果

1. 可本地使用的数据库（首版 SQLite，可迁移 PostgreSQL）。
2. 原始字形图像档案与结构化元数据（JSONL、CSV）；图像与出处可相互追踪。
3. 合规、限速、可断点续传的采集工具；只使用公开可访问且允许自动获取的资源或经过授权的导出资料。
4. 字头和异体字映射、分类、去重与质量检查脚本。
5. 本地查询界面或 CLI：按字头、Unicode、时代、书体、来源检索并查看图像。
6. 自动生成的覆盖率报告、失败请求报告、许可与溯源报告。

### 1.2 不在首版范围内

- 不推断未被学术确认的古今字对应关系。
- 不对缺失的字形进行生成式补全并冒充史料。
- 不声称完成全量古汉字收录，也不承诺每字有全部历史阶段。
- 不绕过验证码、登录、频控、封禁、反爬机制或付费访问控制。

## 2. 数据来源与核验

优先研究以下来源：

- 中央研究院「小学堂」字形演变数据库：https://xiaoxue.iis.sinica.edu.tw/yanbian/Home/Home
- 中央研究院「小学堂」汉字古今字资料库：https://xiaoxue.iis.sinica.edu.tw/ccdb/
- 小学堂平台主页及其专题库：https://xiaoxue.iis.sinica.edu.tw/
- 可作为技术参考的第三方项目：https://github.com/EvaWang/xiaoxue_crawler （只参考代码与思路；不要假设项目仍可运行）
- 如需补充甲骨文字形，可评估「殷契文渊」等专题数据库，但必须逐源核实许可与采集条件。

**Codex 首先必须做来源审计**，并将结果写到 `docs/source_audit.md`：

1. 验证站点与具体入口是否仍有效。
2. 检查版权声明、授权覆盖范围、使用条款、`robots.txt`、可能的官方导出与 API、申请数据途径。
3. 使用浏览器开发者工具或合法的只读探测，确认字头、图像、文献出处是怎样呈现的；记录示例请求、响应类型、页面字段及采集方式。
4. 核对图像是否受单独授权，数据库记录/文献图片与界面字形图片可能享有不同许可；逐来源记录授权证据和访问日期。
5. 如果网站禁止自动化采集，应停止对该站的爬取，并建立**人工/官方导出文件导入适配器**，不得默认抓取。
6. 不要依赖未经实测的 `kaiOrder`、隐藏接口或跨库共用 ID；验证后才写入适配器。

授权适用范围不等于允许无限制自动请求。采用保守的抓取节奏，遵守站点限制与维护方反馈。

## 3. 数据设计

推荐同时保存**原始抓取记录（raw）**与**规范化记录（normalized）**，避免解析规则变化导致历史数据不可重建。

### 3.1 实体模型

- `character`：规范字头（字形、Unicode、繁简关系、标准化策略）。
- `character_alias`：繁简字、异体字、来源内部字头标记等；关联类型必须标注，不能默认严格等价。
- `source`：数据库/馆藏/出版物/版本、授权证据、引用 URL。
- `source_record`：来源站点上的单条原始记录、来源 ID、原始字头、采集时间、页面快照或响应哈希。
- `glyph`：一条学术意义上的字形实例（所属字头、书体、时代/断代、释读可信度、出处、来源记录 ID）。
- `image_asset`：图片文件的路径、MIME、像素尺寸、SHA-256、原始 URL、下载时间、图片许可。
- `glyph_image`：字形实例与图片的一对多/多对多关联。
- `crawl_job`：请求队列、状态、重试数、最后错误、下一次允许访问时间。
- `review_decision`：人工更正与争议记录，保存修改前后值和依据。

### 3.2 关键约束

- `character` 的内部主键与 Unicode 字符不可混同，允许无统一编码的古文字独立记录。
- `period`（时代）、`script_style`（字体/书体）、`date_start`/`date_end`（可为空）、`date_basis` 独立保存；任何年代推测都要标注置信度。
- 同一规范字头可存在多种异体、一对多释读以及跨时期的复杂关系。
- `missing` 要区分：`not_checked` / `not_in_source` / `unresolved_mapping` / `not_attested`（只有有证据时使用）。
- 原图只读保存；若产生裁剪、透明化、缩放版本，作为衍生资产另存并关联源图、处理方法与版本。
- 所有记录应有 provenance（来源和获取过程）。禁止仅存图片而丢失文献出处。

### 3.3 推荐 JSONL 样例（仅作格式示例，不是真实史料）

```json
{"glyph_id":"g_example_001","character":"馬","unicode":"U+99AC","source_id":"sinica_xiaoxue","source_record_id":null,"source_url":null,"period":"bronze_age","script_style":"jinwen","dating":{"start_year":null,"end_year":null,"basis":null},"source_citation":null,"image_path":null,"sha256":null,"license_id":null,"mapping_status":"unverified","review_status":"pending"}
```

不要给未知字段填入看似确定的占位值；实际数据用 `null` 并记录状态。

## 4. 仓库结构（建议）

```text
hanzi-evolution/
├── README.md
├── pyproject.toml
├── .env.example
├── config/
│   ├── sources.example.yaml
│   └── periods.yaml
├── docs/
│   ├── plan.md
│   ├── source_audit.md
│   ├── data_dictionary.md
│   ├── collection_policy.md
│   └── methodology.md
├── src/hanzi_evolution/
│   ├── cli.py
│   ├── db/              # SQLAlchemy models, migrations
│   ├── sources/         # 一个站点一个 adapter
│   ├── crawl/           # 调度、限速、重试、恢复
│   ├── normalize/       # Unicode、繁简、异体、时代与书体
│   ├── media/           # 下载、哈希、校验、衍生图像
│   ├── review/          # 质量核验与审阅结果
│   ├── export/          # CSV / JSONL / 数据清单
│   └── reports/         # 覆盖度、失败、许可、追溯
├── tests/
│   ├── fixtures/        # 小型、合法保存的测试响应
│   ├── test_parsers.py
│   ├── test_models.py
│   ├── test_resume.py
│   └── test_exports.py
├── data/
│   ├── raw/             # 不提交大文件到 git
│   ├── images/original/
│   ├── images/derived/
│   ├── exports/
│   └── hanzi.sqlite
└── scripts/
```

## 5. 技术栈

- **Python 3.11+**；HTTP 客户端 `httpx`（或 `requests`）。
- 静态 HTML 解析：`BeautifulSoup` / `lxml`；**只有页面确实需要 JS 渲染**时才使用 `Playwright`。
- 数据模型：`SQLAlchemy` + `Alembic`；SQLite 首版，保持迁移至 PostgreSQL 的能力。
- 数据校验：`Pydantic`；图像校验：`Pillow`；表格：标准 `csv` 或 `pandas`。
- CLI：`Typer`；测试：`pytest`；日志：结构化日志。
- 将每个数据源设计成独立 adapter（发现字头、分页/详情读取、解析字形、获取图片和许可元信息）；不要把某个站点的 HTML 结构写死在核心逻辑中。

## 6. 爬虫安全、合规及工程规则

1. 启动采集前显式配置 `source.enabled=true` 和许可审计状态；默认 **dry-run**，不发大规模请求。
2. 遵守网站 `robots.txt` 和明确的使用条款；若不允许访问则禁用该来源。
3. 使用可识别的 `User-Agent`、联系邮箱（由使用者配置）及友好的访问方式。
4. 单站点并发默认为 **1**，初始间隔 **5–10 秒**并加入随机抖动；若站点规则更严格，以站点为准。
5. 429 / Retry-After / 403 / 5xx 等响应应按规则退避或暂停；403 不尝试代理轮换、指纹伪装或绕过封禁。
6. 设置每日/每次会话上限与最大重试次数；禁止无界自动枚举 ID。
7. 先持久化 HTML/JSON 原始响应哈希及解析版本（在许可允许的情况下存储原文），再处理字形数据。
8. 下载图片前验证 URL 所属域名、响应 MIME、最大文件大小和文件格式；避免 SSRF、路径遍历及恶意数据。
9. 幂等写入与断点续跑：以 `(source_id, source_record_id, glyph_local_key)` 等稳定联合键约束；请求失败不产生半条成功数据。
10. 不擅自访问登录保护内容、付费资源，也不使用验证码破解。
11. 对图片和元数据分别保存许可证与出处。若许可不明，将内容置为隔离状态，不纳入公开数据包。

## 7. 分阶段执行计划（Codex 必须逐阶段实现）

### Phase 0 — 来源与许可审计

**任务**：核对官网入口与抓取条件；阅读已有 GitHub 项目（仅做参考），分析网页/返回格式；形成 `docs/source_audit.md` 与风险清单。

**验收**：列明能否合法自动采集、可用字段、图像可获取方式、缺失字段、接口稳定性；若信息不完整，不允许推进至大规模抓取。

### Phase 1 — 最小可用架构

**任务**：创建 Python 包、依赖、数据库模型与迁移、源 adapter 接口、基础 CLI、样本 fixture、单元测试。

**验收**：离线使用 fixtures 即可完成 `parse → normalize → save → export`，测试通过；真实请求默认关闭。

### Phase 2 — 100 字试采集

**任务**：用户提供或程序内准备合法来源的100字种子表；启用已审核的来源 adapter，抓取图片与元数据。保留请求日志、失败原因和原始出处。建议兼顾高频字、异体字、资料稀少的字。

**验收**：
- 输出100字的处理状态表（包含失败/无记录）。
- 能对每张已收图像回溯到来源记录或明确标记来源缺失。
- 无损坏图片；手动检查各时期的部分样本；没有因为缺失时期而中止整字处理。
- 形成`reports/pilot_100.md`，统计可获取字头数量、图片数量、按时期覆盖情况、平均耗时及错误率。

### Phase 3 — 1,000 字扩展与映射核验

**任务**：扩至1,000字；完善 Unicode、繁简、异体映射及跨库关联；添加去重（SHA-256 精确去重）、人工核验流程、冲突记录和覆盖率统计。

**验收**：
- 跨库 ID 不被误当成相同字头。
- 从数据库可重建每个字头的出处及图片列表。
- 出具随机人工抽样报告，无法确定的映射置于待审阅状态。

### Phase 4 — 3,000–5,000 字正式建设

**任务**：在许可允许与资源可承受的范围内执行采集；持续断点续跑、每日限额、数据库备份，生成数据导出与版本化清单。

**验收**：
- 汇报**实际有数据字头数**，不把目标字数冒充已完成数量。
- 输出 `characters.csv`、`glyphs.jsonl`、`sources.csv`、`missing_periods.csv`、`dataset_manifest.json`。
- 已成功图像的可打开率 ≥99%；关键映射与来源字段的缺失率分别报告。
- 数据可由 README 描述的命令在新环境中重建。

### Phase 5 — 查询与研究分析

**任务**：提供 CLI 或简单本地 Web 页面，检索字头、来源、时期、书体、不同异体，以及图片预览；自动输出覆盖率矩阵。

**验收**：能展示一个字头的**全部已采集字形**及出处，清楚区分“未检查 / 来源未收录 / 无法确定映射 / 有证据证明未见”的状态。

## 8. 推荐 CLI（Codex 需实现等效命令）

```bash
hanzi init-db
hanzi audit-source --source xiaoxue
hanzi import-seeds data/seeds/characters_100.csv
hanzi crawl --source xiaoxue --limit 100 --dry-run
hanzi crawl --source xiaoxue --limit 100 --execute
hanzi validate-images
hanzi report --output reports/pilot_100.md
hanzi export --format jsonl --output data/exports/glyphs.jsonl
hanzi export --format csv --output data/exports/characters.csv
hanzi lookup --character 馬
pytest
```

实际子命令名称可优化，但须提供等效能力。`--execute` 应强制要求来源审计通过；来源若不允许采集，只允许 `hanzi import-official-export` 等离线导入命令。

## 9. 样本选字策略

- **100字试点**：覆盖常见字与不常见字、简繁对应不同的字、不同古文字收录情况；避免只挑选资料丰富的字造成覆盖率偏高。
- **1,000字扩展**：从公开标准常用字表取样，并建立字表版本号、引用地址与获取日期。
- **3,000–5,000字**：明确目标是现代通用字头集合还是学术选字集合；统一映射规则，但保留来源原字头，绝不把繁简归并直接等同于字形历史相同。

如种子字表有使用限制，先保存字表来源与许可，再进入导入。

## 10. 质量指标与报告

至少自动统计以下指标：

- `seed_count`：待处理字头数；`processed_count`：已查询字头数；`with_glyph_count`：至少一张合格图像的字头数。
- `glyph_count`：字形实例数；`image_count`：原始图片数；`unique_image_count`：按 SHA-256 去重后图片数。
- 各时期/书体的字头覆盖率与图像数量；跨库映射的待审阅量。
- `source_traceability_rate`：可追溯到来源记录的字形占比。
- `image_validity_rate`：可被图像库正常解码的图片比例。
- 失败 URL、HTTP 状态、拒绝访问、疑似重复/错配和未授权项目。

> 数值目标不是可信度替代品：任何可疑的字形释读和演变关系都应该保留“不确定”状态。

## 11. 给 Codex 的任务执行说明（可复制粘贴）

请阅读 `docs/plan.md`，按 Phase 0 → Phase 1 → Phase 2 顺序推进。优先实现**可离线测试的最小可用系统**，再在来源许可和访问规则通过审计的前提下启动100字试采集。不要在尚未核验页面结构时凭空编造 API、请求参数或源字段。已有第三方爬虫仅用于参考，不应直接信任其当前有效性。每一阶段必须：

1. 先写简短的实施计划和本阶段验收清单。
2. 落实代码、测试与 README；执行能运行的测试并记录结果。
3. 输出结果、失败原因、风险和下一步。
4. 若外网受限，使用已获准保存的离线 fixtures 完成 Phase 1，不得把 mock 当成真实采集。
5. 若来源条款不允许采集，请建立官方导出文件的导入路径，停止该来源自动访问。

**当前第一项实际任务**：创建仓库骨架、数据库模型与迁移、`source_adapter` 接口、100字种子表格式、单元测试和 `docs/source_audit.md` 模板。确认数据源页面和许可之后，再实现真实请求解析器。

## 12. 风险与应对

| 风险 | 应对 |
|---|---|
| 官网结构变更，现有爬虫失效 | 源 adapter 隔离；fixture 回归测试；记录解析版本 |
| 自动访问受限 | 采用正式授权/官方导出 + 离线导入路径 |
| 不同数据库字头 ID 不统一 | 单独映射表；以有出处的映射为准；不自动强行匹配 |
| 历史时期与书体混淆 | 分字段存储；必要时记录多标签和年代范围 |
| 某字缺少古文字记录 | 保留缺失状态，不生成假字形 |
| 图像重复或跨来源复用 | 内容哈希去重但保留全部来源关系 |
| 文献图像权利不同于字形图 | 图像单独记录版权声明并隔离未确认资产 |
| 大量图片挤占 Git 仓库 | `.gitignore` 排除原图，提供独立数据包/对象存储方案 |

## 13. 项目完成定义

不以“爬到了多少张图片”作为唯一结果。完成标准是：能稳定导入、检索、导出一个有来源、有年代或时代分类、有实际图像、有权利状态、可抽样核验的汉字历时字形资料集，并能由新开发者通过 README、数据库迁移和测试独立复现核心处理流程。
