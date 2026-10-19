# 来源与访问审计

更新：2026-10-19（Asia/Shanghai）。**13:16:47 对 robots.txt 的只读探测返回 HTTP 401，页面明示“您的IP已被封鎖”；当时按硬停止处理。同日恢复访问后完成扩字，当前数据库50字头、1023条关联、1015张不同原图；最终目录data/dataset_50为50字/919图。**

## 2026-10-19 再次受限：robots HTTP 401 / IP 封禁

本次为扩到50字做首次查询探测，只发送1个 robots 请求，未访问任何查询页、未下载图片、未写数据库。响应为 HTTP 401 / text/html，标题“數位文化中心”，正文明确“您的IP已被 封鎖 ，造成服務無法正常運作”。证据：

- `data/batches/expand_50_probe/preflight.json`
- `data/batches/expand_50_probe/raw/robots-d402076bd2fdd9624dc01034d904c664c69dd0048fc9bae4032c4eef691a093d.response`（SHA-256 `d402076bd2fdd9624dc01034d904c664c69dd0048fc9bae4032c4eef691a093d`）

该状态属于硬停止：不重试、不换代理、不伪装身份、不登录绕过。官方反馈入口 https://ascdc.sinica.edu.tw/contact 。同日恢复访问后，`scripts/expand_50.py` 完成50字扩采；期间一次代理中断按 blocked 停止，单次重试后续跑成功。此前 2026-10-18 的普通404状态不代表当前可用。最终结果见 reports/expand_50.md。

## 官方来源和权利声明

- 平台：https://xiaoxue.iis.sinica.edu.tw/
- 汉字古今字：https://xiaoxue.iis.sinica.edu.tw/ccdb/
- 甲骨文：https://xiaoxue.iis.sinica.edu.tw/jiaguwen/
- 字形演变：https://xiaoxue.iis.sinica.edu.tw/yanbian/
- 版权：https://xiaoxue.iis.sinica.edu.tw/License/License
- 下载：https://xiaoxue.iis.sinica.edu.tw/Download/Download

官方版权页声明查询界面所得各分辨率字形图片及字形属性信息采用 CC0 1.0，不能外推至整部出版物扫描件和不属于该声明范围的资源。逐图许可仍与来源许可分别保存；本轮入库图片的逐图许可未自动确认，映射和审阅状态为 unverified/pending，默认正式导出不含它们。

下载页列有声韵资料、崇羲篆体、台语注音字体及输入法。本轮未确认历时字形图片的官方批量导出或公开 API，不代表官方没有申请渠道。

## 首次探测：地区限制

此前本机 robots 请求返回 HTTP 200 / text/html，标题 Access Restricted | ASCDC，提示当前地区未开放。证据 data/raw/audit/robots.txt，SHA-256：6465bc25b5527f4605db42effef880065e97ee6553bcfc5a68674480f7215781。

当时停止采集。用该页面离线复现，第三方原解析函数返回空 charname/imgList；修补后会明确失败。

## 本轮重试：普通404与查询成功

未切换代理、伪装浏览器身份、登录或绕过验证码。本轮 requests 使用可识别的 HanziResearchDebug User-Agent。

1. robots 返回普通404，标题“數位文化中心”，内容为“網址失效”，不再是地区限制页。证据见 data/thirdparty_debug/probe/jiaguwen/preflight.json 及 raw/ 下原始响应。
2. 首版调试补丁将404也阻断；核对 RFC 9309 2.3.1.3 后修正：404/410 记为 robots 不存在，不等同于禁止；403、429、5xx、受限/验证页面仍停止。协议规则不替代版权和授权判断。参考：https://www.rfc-editor.org/rfc/rfc9309.html#section-2.3.1.3
3. 旧 GET 地址 /jiaguwen?ZiOrder=1 返回301，指向同站 /jiaguwen/?ZiOrder=1。规范地址返回正常首页，但只预填 ZiOrder 输入框，不自动执行查询。
4. 页面真实表单 BasicFrom 的 action 是 /jiaguwen/PageResult/PageResult，method=POST。本轮使用原页面 input[name] 的实际字段提交编号1，非猜测接口。
5. POST 返回 HTML 片段，含 HiddenFrom、ZiOrder=1、PageTo=1 和 VariantListA/B 字形单元格。结果为3字形／1页。
6. 页头 charValue 的标准字形 alt=&0.4E00; 对应“一”；原 ZiOrder=1 单独保留 raw_head，不作为Unicode。
7. 字形图像地址直接来自 img.src 的 /ImageText2/ShowImage.ashx。保持原查询参数，仅沿用原项目 size=64 参数。
8. 实测返回3张不同 SHA-256 的 PNG，尺寸均88×87，RGBA透明背景，解码和哈希检查通过。内容为字库渲染的字形，不是拓片或原物照片。size=64 并不表示最终图像一定64×64。

单条结果出处：鐵148.1；前4.47.6／合10308／賓組；佚434／合37497／黃組。未据组别推断年代。

主系统来源配置 audit_status=import_only。最初第三方 HTTP 模式仅实测一条单页，后续已补齐编号1–10及双页记录，见文末补采结果。金文/小篆、全站条款和长期请求限额尚未完成审计，不能外推全站采集能力。

## 第三方项目和本地修改

- 上游：https://github.com/EvaWang/xiaoxue_crawler
- clone：thirdparty/xiaoxue_crawler，基线 commit 467e72bd471f871b26ee1d904c54ea6bb49ddd7b。
- 用户明确要求本地 clone 和调试；仓库根目录未见 LICENSE，不将修改后的上游代码当作自有代码重新发布。
- 修改 read_font.py、download_img.py、requirements.txt，新增 http_driver.py，保留原 id/charname/imgList 格式并增加来源和响应哈希。
- 真实 HTML 中存在未闭合 td；原 html.parser 会串联相邻字形出处，改用 lxml 后3条出处独立。
- Selenium旧 chrome_options 参数不兼容已修；ChromeDriver下载卡住的线上试跑已终止。当前已验证的采集走普通HTTP表单，不依赖Chrome。

## 证据位置

- 手动单条探测：data/thirdparty_debug/http_single/，包括首页、301、POST的响应和请求字段。
- 修补后入口完整采集：data/thirdparty_debug/collected/jiaguwen/requests.jsonl、raw/、jiaguwen.jsonl。
- 下载证据：同目录 downloads.jsonl、img/1_2.png、img/1_3.png、img/1_4.png。
- 已入库：data/hanzi.sqlite，按哈希归档于 data/images/original/。
- 质量统计：reports/current_quality.json。

原始响应仅本地归档；不随默认公开导出打包。尚未完成100字试点、随机人工抽样、跨库映射或批量吞吐评估。

## 首批有界采集更新

用户后续明确授权批量下载，实际尝试甲骨文编号1–10：1已有记录；5、7、8、9、10完整采集并入库40张新图；2、3、4、6因多页尚未支持未导入。当前合计6个有图字头、43张图片，未遇访问限制，间隔7秒、单站串行。真实多页现已观察到，但未实现翻页；不将部分页面作为完整记录。详细结果和限制见reports/batch_10.md。

## 翻页流程核验

用户要求解决多页逻辑后，读取实际首页已引用的 /Scripts/Site.js、/Scripts/FeedbackScript.js，按原有频率限速。原始脚本本地归档在 data/raw/pagination_audit/，未替换网络身份。

FeedbackScript.js 中 a.Bookmarker 的处理逻辑是：从链接id去掉PageLink前缀取得目标页码，写入隐藏PageTo，再提交HiddenFrom。新HTTPDriver依此读取当前实际HiddenFrom的action、method、input和select选中值，仅修改PageTo，并验证目标恰为当前页加1；不猜测新接口。

解析器逐页归档响应，核对记录编号、连续页码、每页声明的总字形/总页数、跨页重复实例和最后实际总数；字头示意图仅保留一次。失败不返回完整记录，最多读取配置允许的页数。新增测试覆盖两页/三页合并、漏页、错页码、跨页重复和总数不符。

编号2“元”已真实取回两页，解析33字形，与网站总数一致；图片下载和其余失败编号的重试结果以 reports/pagination_retry.md 为准。

翻页补采最终完成：编号2/3/4/6分别解析2页，下载并入库33/22/22/26张，共103张；四条均与网站声明总数一致。全库和当前data/dataset均10字头146图，49项测试通过，最终图片及manifest哈希全部校验。报告reports/pagination_retry.md；主系统仍保持import_only，待审阅状态不变。

## 跨来源 MVP（后续更新）

已核验金文、小篆、隶变、字形演变4个入口和真实BasicFrom表单，并分别用EudcFontChar查询“一、天”；请求/首次结果存于data/raw/cross_source_audit。跨库链接从已归档的官方甲骨文结果页提取，并逐次核对结果标准字头，未假定来源编号统一。

共完整解析14页181字形，包含金文“天”5页81字形；明确按每来源每字头每实际字库分类最多2张抽样，入库34条字形，另保存2条现代標楷體字头参考。实际下载28张，复用8张已有图片。现代楷书参考来源与古文字区分，非历史楷书碑帖/文物。

分类依据为查询图像URL中明确的字库名称及出处标注：隶变含秦系简牍和隶书，說文古文独立于小篆；字形演变另提供战国、楚系简帛等分类，但本轮尚未全面实现这些独立专题库。未知字库或字头错配会停止该MVP，不猜测归类。

当前全库10字头182条关联记录、174张不同原图；资料目录data/dataset已更新。60项测试通过，实际复跑新增下载0、重复入库0。原始来源和图片许可仍分开保存，全部保留待审阅状态；详情reports/cross_source_mvp.md。
