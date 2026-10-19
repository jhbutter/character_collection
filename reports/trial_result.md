# 本轮试运行结果（2026-10-18）

## 结论

已完成可运行的离线数据库最小系统，当前无法通过本机网络从小学堂直接建立真实资料集。Phase 0 的在线访问审计未通过，Phase 2 未启动。

## 实测

- 参考项目下载成功，commit 为 467e72bd471f871b26ee1d904c54ea6bb49ddd7b。
- 官方网页读取工具能读到版权声明，查询界面字形图片及属性信息的声明为 CC0。
- 本机 robots 请求 HTTP 200，但正文为地区访问受限 HTML，未取得有效 robots 规则。
- 将保存的受限 HTML 传给参考项目的原始 get_xiaozhuan_list_url 函数，以离线 driver 替代浏览器；原函数输出 id=1、charname=""、imgList=[]。未发出额外网络请求。
- 新的 inspect-page 识别该文件为 blocked，退出码 2。
- crawl --execute 在来源未通过审计时退出 2，network_requests=0。
- pytest：17 passed in 4.19s。
- 正式数据库 data/hanzi.sqlite 初始化成功，真实字形和图片均为 0。
- 独立演示库 data/demo/hanzi.sqlite 成功导入 1 条合成记录、1 张合成方块图；重复导入跳过 1 条，没有重复字形。
- 演示图片解码及哈希校验通过，完整率 1.0；此数值只描述测试图，不是实际采集质量。
- 显式 include-test 导出 JSONL / CSV 各 1 行；默认正式导出为 0 行。

质量报告：reports/current_quality.json（正式空库）、reports/demo_quality.json（独立测试库）。

## 后续条件

由官方提供可使用的字形导出，或明确可访问和允许采集的条件后，再核验真实页面、分页、字头映射和逐图许可，并进行100字试点。现有库可以直接接收本项目规范化 JSONL，以及第三方项目已有的本地 JSONL/图片。尚无 Web 界面、在线下载器或完整人工核验流程。
