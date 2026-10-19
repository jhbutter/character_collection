# 项目实施约定

- 解释使用中文，技术标识符保留英文；文件编辑使用 Bash heredoc。
- 优先修改现有代码，不主动 commit 或 push。
- 本项目为 Python 包；Python 变更用 `.venv/bin/pytest -q` 验证。
- 主系统：SQLAlchemy Core、Alembic、Pydantic、Typer、Pillow。
- `schema_v1.py` 是 0001 的冻结结构，后续数据库变更新增 Alembic 修订。
- 第三方仓库位于 thirdparty/xiaoxue_crawler，保留其独立 Git 历史，基线467e72bd471f871b26ee1d904c54ea6bb49ddd7b；本地修改未提交。
- 用户明确要求 clone 并调试第三方项目，允许本地修改它；上游未见 LICENSE，未经另行核验不对外重新发布其代码。
- 已验证普通HTTP表单及编号1–10批次，翻页修复补回103张；甲骨文10字头146条记录。跨库MVP阶段曾为182条图像关联、174张不同原图；十字补采后336条关联、328张不同原图；扩字完成后当前为50字头、1023条关联、1015张不同原图。结果见reports/cross_source_mvp.md，当前基线见reports/current_quality.json。历史地区限制并不代表现在仍受限；每轮按实际响应判断。
- 2026-10-19 13:16:47 对 robots.txt 的只读探测返回 HTTP 401，页面明示“您的IP已被封鎖”；当时按硬停止处理并保留证据 data/batches/expand_50_probe/preflight.json。同日恢复访问后完成扩字；期间一次代理中断按 blocked 停止，单次重试后续跑成功。
- 采集实现位于 src/hanzi_evolution/collection/；scripts/*.py 仅为兼容入口，保持原命令可用。
- scripts/expand_50.py 为扩到50字入口：默认 11–60（11–50为主，51–60补足），甲骨文每字≤5，四个跨来源，目标50个有图字头，每批≤100张，默认输出 data/dataset_50，不覆盖 data/dataset；默认 dry-run，重复执行可续跑。等价 CLI 为 hanzi collect-expand50；旧 hanzi crawl 仍只做 dry-run。
- 零结果仅在页面明确“共搜尋到 0 字”且无 VariantList/StartOrder 时记为 no_result；缺少结构、受限页或验证码仍按失败/停止处理，不把未知页记成来源未收录。
- read_font.py 默认不联网，显式 --execute 执行。robots普通404按不存在处理；403、429、5xx、受限页及验证码必须停止，不绕过限制。
- HTTP多页已按官网HiddenFrom/PageTo流程实现，编号2、3、4、6的两页记录均验证并下载入库。每页核对编号、连续页码、总数和跨页重复；金文、小篆、隶变、字形演变已对当前50字完成查询，继续扩大字表仍需新的首次查询核验，不自动扩大采集规模。主系统新增 hanzi collect-expand50 显式入口；旧 hanzi crawl 仍只做 dry-run。
- 测试额外依赖见 thirdparty/xiaoxue_crawler/requirements.txt；第三方回归用合成HTML，不联网。
- 合成样本 is_test=true 并使用独立数据库，不得冒充真实字形。
- 真实样本仍 mapping_status=unverified、review_status=pending；不凭空填断代、出处或逐图许可。
- 不自动归并繁简异体，不将站内编号当 Unicode；来源字库渲染图不等同于拓片或原物照片。
- 推送前更新 README.md 和 AGENTS.md；大文件、原图、数据库和 .venv 不入库。
- 用户已明确最终交付结构为“每个汉字一个文件夹，内部按甲骨文、金文、小篆、隶书、楷书等字形阶段存放图片”；使用 `hanzi export --format tree`，最终样本输出到 data/dataset_50，data/dataset 保留 10 字历史快照。
- 目录按 script_style 分字形阶段，缺少分类用“待分类”；具体断代 period 及年代依据仅保存在metadata.jsonl。每字保留出处/许可/审核元数据，根manifest布局为character-stage-v1。旧目录备份data/dataset_period_v1已于2026-10-18清理。
- 目录导出为快照；相同内容可复用，内容不同使用新版本目录，不覆盖用户文件或混入旧图片。
- 用户已授权尝试批量下载；首批甲骨文编号1–10已完成，每批最多100张新图片、默认7秒间隔。入口 scripts/batch_collect.py，状态逐条落盘；来源限制立即停止，记录级解析失败继续后续编号。
- 批次入库必须逐来源记录归档JSONL，避免将已入库编号放进不同整文件哈希而触发冲突；未完整下载/未完成分页的记录不记成功。

- 跨库MVP阶段为182实例文件（174张不同原图）；相关历史快照data/dataset_cross_source_mvp、data/dataset_pagination_complete、data/dataset_before_cross_source_mvp、data/dataset_batch_10均已于2026-10-18清理。扩字后当前基线为50字头、1023条关联、1015张不同原图，所有记录仍待审阅。

- 批次报告按folder.name保存到reports/<批次名>.json，不覆盖reports/batch_10.json等历史结果。分页重试原始记录在data/batches/jiaguwen_multipage_002_004和jiaguwen_multipage_006。

- 跨库MVP入口scripts/cross_source_mvp.py，已审计首结果在data/raw/cross_source_audit，完整页面/抽样声明在data/batches/cross_source_mvp/records。按结果标准字头匹配，不共享来源编号。
- 跨库MVP阶段每来源每字头每实际分类最多抽样2张，完整解析181字形不代表全部下载；后续十字补采按每字每字体跨来源合计最多5张。缓存保持原始输入，复跑已验证不增加下载/记录；扩大字表需要新的首次查询核验。
- 隶变库包含多种字库，按逐图字体名称和出处分类；说文古文独立于小篆。modern_reference仅为“现代楷书参考”，不冒充历史楷书资料。
- 新来源断代仅抄录单元格明确标签，date_basis记录原文，不推断年代边界。跨库重复图保留各出处，内部image_asset按哈希去重；导出文件数和不同原图数分别报告。

- 最终tree目录统一按“汉字 + 字体目录”跨来源/具体年代最多5张，按glyph_id升序选择，不足不补；适用于CLI、甲骨批次及跨库MVP的目录导出。原始档案、数据库及CSV/JSONL完整导出保留全部记录。
- 扩字已完成：数据库50字头、1023条关联、1015张不同原图；data/dataset_50为50字、919图；data/dataset保留10字、232图历史快照；data/dataset_50_smoke11保留11字、244图烟测快照。11–64中PUA-only或无法确认Unicode的编号跳过，61–64用于补足。所有记录仍待审阅，publishable_glyph_count=0。81项离线测试通过，包括零结果、PUA/多字头选择、限额、复跑、CLI dry-run 与封禁路径。

- 2026-10-18 用户要求清理冗余，已删除9个历史dataset快照（968个重复图片文件）。当前保留 data/dataset（10字/232图历史）、data/dataset_50（50字/919图最终）和 data/dataset_50_smoke11（11字/244图烟测）；上文的旧快照/备份路径为历史记录。数据库、data/images、data/raw、data/batches保留用于追溯及复跑。

- 十字补采已完成：一上旁下示彔元天吏帝，金文/小篆/隶变/字形演变40组查询全部complete。当时data/dataset为232图（每字每字体≤5），数据库336条关联、328张不同原图。新增154条关联/154张新原图，现代楷书参考共10张仍独立于历史楷书。
- scripts/complete_ten.py默认不联网，--execute补采已核验10字，默认输出data/dataset；每批最多100张新图，7秒间隔。记录在data/batches/complete_ten；以原编号:fill5-v1作为补充导入local_id，原编号另存raw_head及包source_record_id，不覆盖既有证据。来源不足5张如实记录。
- 已清理data/demo、data/demo_input、data/exports和.DS_Store，以及本轮中间快照。65项测试通过，复跑0下载/0新增，数据库和档案哈希检查通过。详见reports/complete_ten.md。历史的78图、182图等描述仅为阶段性记录。
