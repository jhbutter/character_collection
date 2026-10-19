# 汉字历时字形资料库

本地 SQLite 系统，加上 `thirdparty/xiaoxue_crawler` 中直接调试的第三方采集项目。完整规划见 [docs/plan.md](docs/plan.md)。

**当前数据库50个字头、1023条图像关联记录、1015张不同原图。** 50字交付目录 `data/dataset_50` 为919张图片；按字体优先布局 `data/dataset_50_by_style` 同为50字/919图；10字历史快照 `data/dataset` 保留232张。已完成甲骨文编号1–10，并从11–64号中补出40个新增字头；同时完成金文、小篆、隶变、字形演变4个来源的查询，含50条明确分离的现代楷书参考。最终目录按每汉字每字体最多5张筛选，图片校验通过。映射、逐图许可和学术对应关系仍待审阅，默认正式导出不包含这些待审记录。这是50字的阶段性验证，不是100字试点或完整数据集。

2026-10-19 曾对 robots 的只读探测返回 HTTP 401，页面明示本机 IP 被封禁；同日恢复访问后完成扩字。期间修正了 PUA 外字覆盖标准字头、多个标准字头选择、空 `StartOrder` 零结果页等问题，详见 [来源审计](docs/source_audit.md)。

此前遇到过地区限制页；本轮重新探测时 robots 返回普通404，公开查询表单和图片已可访问。详见 [来源审计](docs/source_audit.md) 和 [第三方调试报告](reports/thirdparty_debug.md)。

## 安装

Python 3.11+；本次实测 macOS arm64 / Python 3.14.6。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --index-url https://pypi.org/simple -e '.[test,collection]'
python -m pip install --index-url https://pypi.org/simple -r thirdparty/xiaoxue_crawler/requirements.txt
hanzi init-db
pytest -q
```

第三方仓库已 clone，保留它自己的 Git 历史。尚未发现上游明确的 LICENSE，当前修改供本地调试，不将其代码当作本项目原创代码发布。需要重新 clone 时见第三方调试报告；直接 clone 只得到原版，不包含本地修补。

## 项目结构

```text
src/hanzi_evolution/     核心包：schema、导入/导出、结果页解析、CLI
  collection/            采集编排：batch、cross_source、complete_ten、expand
scripts/                 兼容入口，实现位于 src/hanzi_evolution/collection/
config/                  来源配置
docs/                    规划、架构、数据字典、来源审计、thirdparty 说明
reports/                 运行报告与质量基线
tests/                   离线测试
thirdparty/              独立 Git 克隆；根仓库忽略，补丁见 patches/
data/                    运行时数据库、原图、批次、交付快照；根仓库忽略
patches/                 thirdparty 本地补丁
```

- 架构与调用链：[docs/architecture.md](docs/architecture.md)
- 采集实现：[src/hanzi_evolution/collection/](src/hanzi_evolution/collection/)
- thirdparty 基线与补丁：[docs/thirdparty.md](docs/thirdparty.md)
- 采集入口索引：[scripts/README.md](scripts/README.md)

## 查看本轮真实样本

```bash
hanzi lookup --character 一
hanzi validate-images
hanzi report --output reports/current_quality.json
hanzi export --output data/exports/real_review.jsonl --include-quarantine
```

数据库 `data/hanzi.sqlite`。真实采集原始响应、请求日志、JSONL 和下载记录位于 `data/thirdparty_debug/collected/jiaguwen/`，原图在其中的 `img/`；入库后另有按哈希归档的原图。原图是来源字库渲染的字形图，不是甲骨原物照片或拓片整图。

## 复现第三方单条采集

```bash
python thirdparty/xiaoxue_crawler/read_font.py --probe \
  --save_path data/thirdparty_debug/collected
python thirdparty/xiaoxue_crawler/read_font.py --execute --transport http \
  --font jiaguwen --start_idx 1 --limit 1 \
  --save_path data/thirdparty_debug/collected
python thirdparty/xiaoxue_crawler/download_img.py --execute --limit 3 \
  --file_list data/thirdparty_debug/collected/jiaguwen/jiaguwen.jsonl \
  --save_path data/thirdparty_debug/collected/jiaguwen
hanzi import-legacy data/thirdparty_debug/collected/jiaguwen/jiaguwen.jsonl \
  --source-config config/xiaoxue_jiaguwen.json --collection jiaguwen \
  --image-root data/thirdparty_debug/collected/jiaguwen/img
```

`--limit` 在 read_font.py 中是结束编号，在 download_img.py 中是图片数量上限。默认不联网，显式 --execute 才执行；请求间隔默认7秒。重复执行跳过已写入的编号。当前 HTTP 模式已验证甲骨文编号1–10，包括4个双页字头；按真实HiddenFrom/PageTo表单翻页并核对字形总数、页数及重复实例。金文、小篆、隶变和字形演变已有独立跨来源入口，当前50字均已完成查询；继续扩大字表及Selenium线上模式仍需验证。

修复了旧 GET 仅预填表单却不查询、未闭合 td 导致出处串联、站内编号冒充字头、Chrome 参数过时、文件名写死及错误页空成功等问题。常规 HTTP 即可完成本条查询，无需浏览器。ChromeDriver 下载卡住的试跑已终止。

主系统的 `hanzi crawl` 尚未接入该第三方采集器，仍仅 dry-run；独立批次入口已验证10字头，主CLI接入、长期调度和全站访问审计尚未完成。

## 导入其他本地资料

```bash
hanzi import-legacy /你的路径/jiaguwen.jsonl \
  --source-config config/xiaoxue_jiaguwen.json \
  --collection jiaguwen --image-root /你的路径/img
hanzi import-official-export /你的路径/records.jsonl \
  --source-config /你的路径/source.json --image-root /你的路径/images
hanzi import-seeds data/seeds/characters_100_template.csv
hanzi export --format csv --output data/exports/glyphs.csv
```

来源专题库分别配置不同 ID，不推定跨库编号相同。标准 JSONL 契约见 [数据字典](docs/data_dictionary.md)；实际官方文件格式需要对应 adapter。种子模板只有表头，未准备100字。所有未知断代保持 null；不自动归并繁简或异体。

默认导出只包含非测试、映射 verified、审阅 approved、有出处和原图、逐图 CC0 及证据 URL 完整的记录。`--include-quarantine` 用于内部审阅；合成数据还必须显式 --include-test。

## 独立合成演示

```bash
python scripts/create_demo_image.py
hanzi import-official-export examples/demo.jsonl \
  --source-config examples/demo_source.json --image-root data/demo_input \
  --db data/demo/hanzi.sqlite --root data/demo
hanzi lookup --character 馬 --include-test --db data/demo/hanzi.sqlite
```

演示库和正式库分开；合成方块图不是汉字史料。使用自定义 --db 时，图片校验/报告等命令同步指定 --root。

## 后续工作

尚未完成100字试点、跨库字头映射、人工审阅界面、完整缺失状态表、Web 预览和正式数据包。历史试运行报告保留原时间状态，以本轮报告和 current_quality.json 为准。原图、数据库和 .venv 不入 Git；不主动 commit 或 push。

## 最终交付目录（按字头与字形阶段）

最终资料集采用“每个汉字一个文件夹，内部按甲骨文、金文、小篆、隶书、楷书等字形阶段保存图片”的结构。SQLite和按哈希归档的原图属于内部存储，目录资料集通过以下命令生成：

```bash
hanzi export --format tree --output data/dataset_50 --include-quarantine
```

本地现有1023条字形关联记录尚待审核，所以内部检查显式使用 --include-quarantine；正式对外导出省略此参数并使用新的输出目录。测试数据默认排除。

当前实际目录：

```text
data/dataset_50/
├── manifest.json
└── 一/
    ├── metadata.jsonl
    └── 甲骨文/
        └── 甲骨文__<稳定标识>.png  （4张）
```

目录按 script_style 映射成“甲骨文、金文、小篆、隶书、楷书”等阶段；缺少分类时使用“待分类”。当前50个字头均有甲骨文；这50字在金文、小篆、隶变、字形演变四个来源均已完成查询，覆盖金文、小篆、隶书、说文古文、秦系简牍、楚系简帛、战国文字等分类。“说文古文”和“现代楷书参考”单独分类。具体历史断代 period、date_start/date_end 和依据仅保留在元数据，不影响字形阶段归类。没有图片的阶段不创建空目录，同一阶段可保存多张原图。

每字 metadata.jsonl 逐图保留出处、来源URL、书体、年代依据、审核和许可状态、SHA-256；image_path 相对于该汉字目录，archive_image_path 指向内部原图档案。根 manifest.json 记录实际字头/字形/图片数量、包含待审/测试数据的标志和导出文件哈希。

目录作为一个快照发布：先校验原图，再构建临时目录，成功后发布。相同内容重复导出会复用；目标目录已有不同内容时不会覆盖或混入旧数据，新增批次请导出到新版本目录，例如 data/dataset_v2。没有确定字头或没有本地图片的行不会被编造归属，跳过数量写入manifest。

旧版按具体断代分组的样本快照 data/dataset_period_v1 已于 2026-10-18 清理；当前 data/dataset_50 使用 character-stage-v1 布局，data/dataset_50_by_style 使用 style-character-v1 布局，data/dataset 保留10字历史快照。

### 按字体分组布局

如果希望“一种字体一个目录，目录里放当前字体已有的不同字头”，使用：

```bash
hanzi export --format tree --layout style \
  --output data/dataset_50_by_style --include-quarantine
```

结构为：

```text
data/dataset_50_by_style/
├── manifest.json
├── 甲骨文/
│   ├── 一/
│   │   ├── metadata.jsonl
│   │   └── 甲骨文__<稳定标识>.png
│   └── 上/
├── 金文/
│   ├── 一/
│   └── ...
└── ...
```

每个字体目录只包含该字体实际有图片的汉字；每个汉字目录内保存该字体下的图片和 `metadata.jsonl`。仍沿用每字每字体最多 5 张、SHA-256 校验和“新内容用新目录”的快照规则。当前生成结果为 10 个字体目录、50 字、919 图。

## 有界批次试采

用户已授权尝试批量下载，目前用独立批次入口对甲骨文来源编号1–10做试点：

```bash
python scripts/batch_collect.py --execute --start 1 --end 10 --max-images 100 \
  --output data/dataset_next
```

单站串行，默认间隔7秒；每批最多100个编号、100张新下载图片。已在库的来源编号跳过；每条完整记录使用独立JSONL归档和事务入库，避免与原单条样本的文件哈希冲突。图片下载未完成或分页完整性检查失败的记录不记为成功，失败记录允许继续后续编号；403/429/5xx、受限页或网络不可用时停止该批次。

运行状态实时保存在 data/batches/jiaguwen_001_010/status.json，逐条下载记录为 downloads.jsonl。报告按批次目录名保存到 reports/<批次名>.json；首轮历史报告为 reports/batch_10.json 和 reports/batch_10.md，包含每个编号状态、实际下载数量、未尝试编号和全库质量指标。输出是按“汉字/字形阶段”组织的内部待审快照；逐项汇报实际成功数量；本轮已补齐编号1–10的全部4个分页失败项。

首批历史结果为新增40张、当时全库43张；历史快照data/dataset_batch_10已清理。多页补采后当时data/dataset为10字头146图，补采前43图备份data/dataset_before_pagination同样已清理；详细结果见reports/pagination_retry.md。

翻页修复已通过49项测试并完成4个双页字头的真实补采。原始采集目录为data/batches/jiaguwen_multipage_002_004和data/batches/jiaguwen_multipage_006；历史完整快照data/dataset_pagination_complete已清理。

## 跨来源 MVP（已实测）

```bash
python scripts/cross_source_mvp.py --execute --per-style 2 --max-images 100
```

固定使用已核验的“一、天”及金文、小篆、隶变、字形演变4个来源。完整解析14页181字形，每来源每字头每实际分类最多抽样2张：本轮入库34条字形和2条现代参考，新下载28张、复用8张。此命令读取本轮归档的首个查询结果并按真实表单继续翻页；缓存复跑新增下载0、重复入库0。扩大字表前仍需增加首次查询和来源核验。

跨库MVP阶段的资料目录为data/dataset；相关历史快照data/dataset_cross_source_mvp及原146图备份data/dataset_before_cross_source_mvp已清理；扩字后当前最终目录为data/dataset_50。详细结果、数量口径和限制见[跨来源MVP报告](reports/cross_source_mvp.md)。原始结果、完整页面和抽样声明在data/batches/cross_source_mvp/records/，来源首页和首次查询审计在data/raw/cross_source_audit/。

隶变来源混合了秦系简牍文字和隶书，按实际字库分类；说文古文独立于小篆。目录中的“现代楷书参考”是网站標楷體字头渲染图，非历史楷书文物/碑帖图片。数据库、JSONL和每字metadata保留出处、来源身份、原始断代标签及审核状态。

### 每字每字体图片上限

`hanzi export --format tree` 统一按“汉字 + 字体目录”跨来源、跨具体年代合计最多保留5张，按 `glyph_id` 入库顺序优先选择；不足5张保留实际数量，不补图。目录元数据仅包含选中的图片记录，manifest记录上限及跳过数量。该上限约束最终目录，采集原始档案、数据库和CSV/JSONL完整导出仍保留全部记录。

限额调整时 `data/dataset` 曾更新为10个汉字、78张图片，排除104条超限图片关联；旧182图目录备份 `data/dataset_before_max5` 已清理。未来批次和跨库脚本均通过同一目录导出函数执行该上限；已有不同内容的快照仍需使用新目录导出。

2026-10-18 已清理历史冗余：删除上述历史dataset快照，包括dataset_batch_10、dataset_before_batch_10、dataset_before_cross_source_mvp、dataset_before_max5、dataset_before_pagination、dataset_cross_source_mvp、dataset_pagination_complete、dataset_pagination_part1和dataset_period_v1。当时仅保留data/dataset作为交付目录；扩字后新增data/dataset_50，文档中其他快照路径仅为历史记录，已不可访问。数据库、内容寻址原图和采集原始记录保留，可按需要重新导出。

2026-10-18 已按用户要求删除data/demo、data/demo_input、data/exports以及data下的.DS_Store；演示数据可通过examples和scripts/create_demo_image.py重新生成。补采当时10字的入口为 `scripts/complete_ten.py --execute`，按已审计查询表单逐字核对字头、验证所有分页，按跨来源总量最多5张选择缺失字体；每批最多100张新图，7秒间隔。来源原编号保留在raw_head和原始包source_record_id；补充导入local_id使用`:fill5-v1`后缀，与早期抽样记录分开归档，避免覆盖原始证据。

十字补采现已完成：一、上、旁、下、示、彔、元、天、吏、帝在已接通四来源的40组查询全部通过，当时data/dataset为232图，每字每字体最多5张。新增154条关联/154张原图；内部数据库336条关联、328张不同原图。现代楷书参考独立分类；来源不足5张不补造。补采入口默认输出data/dataset；复跑已验证0下载、0新增入库。临时补采快照均清理，只保留当前交付目录。详见[十字补采报告](reports/complete_ten.md)。

## 扩展到 50 字（已完成）

目标是把当前 10 字扩展到 **50 个有图片的字头**，从甲骨文编号 11 起顺序补采。甲骨文每字最多 5 张，再为这 50 字补金文、小篆、隶变、字形演变四个来源；每批最多 100 张新图，重复执行可续跑。入口为 `scripts/expand_50.py`：

```bash
python scripts/expand_50.py                 # dry-run，不联网
python scripts/expand_50.py --execute       # 默认 11–60；11–50 为主，51–60 仅用于补足
python scripts/expand_50.py --execute --end-id 50   # 严格只做 11–50

# 等价的 CLI 入口；仍默认 dry-run
hanzi collect-expand50
hanzi collect-expand50 --execute
```

已按 11–64 号完成 40 个新增字头；11–60 中 PUA-only 或无法确认 Unicode 的编号跳过，61–64 用于补足。最终 `data/dataset_50` 为50字、919图；数据库1023条关联、1015张不同原图。所有新记录仍是 unverified/pending，逐图许可为空，属于内部待审快照。完整覆盖、跳过编号和零结果清单见 [扩字最终报告](reports/expand_50.md)。
