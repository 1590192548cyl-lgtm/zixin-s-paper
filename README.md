# 分行业信息披露监管与股价同步性

私密论文交接仓库。交接与资料更新：2026-11-12；最新已完成实证审计：2026-11-09。

## 先读导师指引

**[导师选题指引 在线阅读版](ADVISOR_GUIDANCE_FIRST.md)** · [导师原件 Word](Advisor_Topic_Guidance.docx)

导师建议的论文主线是：研究分行业披露监管是否降低股价同步性，并以**财报文本相似度**衡量披露趋同，进一步考察趋同程度较高时，监管改善定价效率的作用是否被削弱。具体表述以导师原件为准。

Gao与黄炳艺两篇论文是两条方法和制度参照路径，不是两个必须同时取得显著结果的独立论文题目。当前冻结结果主要处于主效应与识别审计阶段；文本相似度调节检验尚未在交接结果中核实为完成，不能写成已有结论。

## 给接手AI的第一入口

请读取 **[AI_HANDOFF_PROMPT.md](AI_HANDOFF_PROMPT.md)**。第一轮只阅读、核对和汇报，不自动改数据、重算SYN或重跑回归。

建议阅读顺序：

1. [导师指引](ADVISOR_GUIDANCE_FIRST.md)：论文目标及创新点。
2. [研究进度](CURRENT_STATE.md)与[模型及变量口径](MODELS_AND_VARIABLES.md)：已完成什么，各版本如何区分。
3. [结果台账](RESULTS_LEDGER.md)与[最新来源审计](latest_source_audit.md)：哪些结果可以引用，哪些识别问题仍存在。
4. [下一步](NEXT_STEPS.md)及[缺失清单](MISSING_INPUTS.md)：继续工作的前提和停止条件。
5. [数据入口](ANALYSIS_DATA_START_HERE.md)、[最小重建包](MINIMAL_REBUILD_START_HERE.md)及[运行顺序](RUN_ORDER.md)：文件怎么还原、哪些程序不能直接启动。

## 两条研究路径与当前结果

|冻结版本|研究设计|静态系数|p值|原估计样本|政策前联合p|
|---|---|---:|---:|---|---:|
|Gao方向 四批次G1|具体IIDG的stacked DID；Size、MB、Lev；firm×stack与cohort×year FE；公司聚类|-0.056769|0.046419|24,659 stack行；1,770公司|0.259737|
|黄文方向 H8过渡版|2015年上交所改革；原八控制；2014单列过渡项；公司/年份FE；公司聚类|-0.091672|0.036264|7,609公司年；648公司|0.000949|
|黄文方向 2008基线DR-DID|原H8 Treat；2008真实基线完整；2013与观察后期均值比较|-0.049154|0.519993|513家公司；形成1,026个两期行|0.013833|

G1保留2013、2015、2016、2017四批次，事件窗[-3,+2]，基准-3。H8事件基准为2013，2014单列过渡；DR也以2013为前基准，但将2014排除在前后比较之外。**不能混用三者的样本、SYN、控制时点、权重或基准。**

G1仅名义5%显著，不是三星；H8与DR在5%水平拒绝政策前联合为0。未拒绝前趋势也不证明平行趋势成立。现有结果不是作者确认的样本级精确复刻，不能为显著性筛选模型或隐去历史探索。

## 数据与代码如何使用

可直接读取的冻结面板：

- [G1_analysis_frozen.dta](G1_analysis_frozen.dta)：含26,711存储行，原回归样本标志对应24,659行。
- [H8_analysis_calendar_fixed.dta](H8_analysis_calendar_fixed.dta)：含7,884存储行，按old_H8_sample==1识别原7,609行。
- [DR_analysis_wide_2008.dta](DR_analysis_wide_2008.dta)：513行公司宽表，不要误认作年度面板或1,026行两期表。

完整文件分三层：

1. **代码与汇总结果**：[GitHub_upload_only.zip](GitHub_upload_only.zip)保留原目录结构，包含代码、表图和早期交接说明；[package_manifest.json](package_manifest.json)为其主体文件校验清单。
2. **分析数据与来源**：全部`analysis_data_*`分包及[ANALYSIS_DATA_MANIFEST.json](ANALYSIS_DATA_MANIFEST.json)。含公司名单、排除原因、权重、影响函数、日志与选定原始表。按[数据说明](ANALYSIS_DATA_START_HERE.md)先还原分片，再解压。
3. **新增原始来源及路径准备**：全部`minimal_sources.zip.part*`、[MINIMAL_REBUILD_ARCHIVE.json](MINIMAL_REBUILD_ARCHIVE.json)和[最小重建说明](MINIMAL_REBUILD_START_HERE.md)。版本依据见[RAW_VERSION_AUDIT.json](RAW_VERSION_AUDIT.json)，路径对应见[REBUILD_INPUT_REGISTER.json](REBUILD_INPUT_REGISTER.json)。

开题答辩PPT和两篇论文见[参考资料入口](REFERENCES_START_HERE.md)。软件、原程序与运行限制见[REPRODUCIBILITY.md](REPRODUCIBILITY.md)。

还原、校验和准备工作副本不等于运行实证。历史脚本含绝对路径、缓存依赖和一次运行保护，不得直接批量执行，也不得删除标记或绕过断言。

## 当前未决问题与下一步

优先补核真实ST状态历史和早期P0207行业回溯口径；确认客观错误后，先列出唯一修复方案供用户确认，不自动重跑。

- ST历史核验的完整下载目标为[922家公司清单](ST_download_candidates922.csv)，不是估计样本或应删名单。现有公司基本信息表重新上传后，原覆盖不足问题仍然存在。
- 238条早期P0207实施日期记录不等于全体公司的完整年度分类。不能多数映射或前后填充。
- 601607继续暂缓；证据不足的两职合一不得赋0。
- 没有取得作者确认的完整名单；尚未执行干净环境端到端数值复现。
- 导师的文本相似度调节方向需要单独核对定义、时点和可用文本。全量原始年报未上传，不应自动重扫或据此声称该模块已完成。

目前有继续研究的核心面板及补充原始表，但不是已经验证的一键从头重建流水线。[MISSING_INPUTS.md](MISSING_INPUTS.md)区分了已补归档的来源、仍待外部证据的问题和工程依赖。

## 仓库边界与历史记录

**保持Private，仅向具有相应数据与资料访问权限的合作者开放。** CSMAR原始/派生数据、导师内部指引、开题材料和参考论文均不因此获得公开转载许可。

本仓库现已包含分析数据、原始来源、开题PPT及两篇参考论文。旧交接ZIP及部分历史说明中“未上传微观数据/版权论文”等文字，是当时的分发状态记录，不是当前清单。原快照不改写；本README说明当前状态。

首页整理前的版本保存在[README_HISTORY_20261112.md](README_HISTORY_20261112.md)。本次只调整资料顺序、说明和交接入口，不修改原数据、控制公式、样本、政策时点、模型或既有结果。
