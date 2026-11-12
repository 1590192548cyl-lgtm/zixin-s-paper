# 最小可重建资料补充｜2026-11-12

这是原始来源与路径准备补充，不是新一轮实证。原数据、SYN、控制值、处理组、样本、缩尾点及所有结果均保持不变。本轮没有运行变量构造、SYN或回归。

## 一、补了什么

- 原Gao程序读取的控制变量原表：补齐此前未上传的利润、现金流、EPS、扣非、年度市值、月收益、第一大股东、分析师、两份子公司表。
- 黄文原输入：年度前十大股东分片ZIP及其字段说明、原公司基本信息/控制人/股本补充ZIP，以及原换手率、控制人表。
- 既有年报索引与MD&A状态元数据，不重新扫描年报。
- 版本核验记录、同名文件比较、原SQLite检查点来源登记、统一路径配置、只做输入准备的辅助程序和运行顺序。

此前已上传且字节相同的来源不重复打包。REBUILD_INPUT_REGISTER.json给出每个旧路径对应的包内文件与SHA256。

## 二、版本结论如何理解

原检查点的15项来源均与当前文件的“字节数:mtime纳秒”一致。有历史SHA256的记录另做了严格内容哈希核对；其余只标注检查点签名一致、本次固定SHA256，不冒称已经证明完整历史内容同一。

- 利润表采用原程序的`营业利润净利润/FS_Comins.xlsx`，不使用内容不同的`营业收入_净利润/FS_Comins.xlsx`。
- 两份年度TRD_Year.xlsx的哈希相同；保留原程序的`总市值`路径。
- 黄文4个补充ZIP与原H8输入清单SHA256一致。ZIP内CSMAR“版权声明.pdf”原样保留，这是数据许可说明，不是新增参考论文。
- MD&A状态文件只是当前既有元数据快照，不声称有历史SHA256。

详见RAW_VERSION_AUDIT.json、DUPLICATE_FILENAME_REVIEW.json。文件移动后的mtime不能当作内容哈希；校验以随包SHA256为准。

## 三、先恢复文件，再做只读检查

将下面所有文件下载到同一目录，不能只下载本说明：

1. 原GitHub_upload_only.zip和全部analysis_data_*，原ANALYSIS_DATA_MANIFEST.json、restore_large_archives.py。
2. 本次全部minimal_sources.zip.part*、MINIMAL_REBUILD_ARCHIVE.json、restore_minimal_sources.py。
3. REBUILD_INPUT_REGISTER.json、configure_rebuild.py、rebuild_paths.json。

可在有权限的本地目录先执行以下**文件还原/只读检查**，这些命令不构造任何经济变量或运行Stata：

```bash
python3 restore_large_archives.py
```

将原全部analysis_data_*.zip逐个解压到同一目录，得到`analysis_data/`。不要把外层目录嵌套两次。然后：

```bash
python3 restore_minimal_sources.py
python3 configure_rebuild.py --config rebuild_paths.json
```

第二条默认只读，所有登记文件必须存在且SHA256一致。缺失/变更会退出并逐条报告，不能自动找同名替代。

## 四、路径配置与工作副本

rebuild_paths.json中`package_root`为下载和解压后的目录（默认`.`），`working_root`为**新的、尚不存在的工作目录**（默认`rebuild_workspace`）。`execute_analysis`固定为false。不要指向原论文目录或已经保存结果的目录。

如确需准备隔离副本，可在确认输入检查通过后执行：

```bash
python3 configure_rebuild.py --config rebuild_paths.json --materialize
```

此命令只复制已校验的输入和工作文件，生成路径替换后的工作代码，不运行这些代码。原始下载快照不改。对应关系为：

|旧路径根|新工作目录|
|---|---|
|原Desktop/毕业论文|rebuild_workspace/thesis|
|原Desktop/控制变量|rebuild_workspace/thesis/控制变量|
|原Documents/New project|rebuild_workspace/workspace|
|原Desktop/2008年控制变量下载清单_20261104|rebuild_workspace/baseline_2008|

只替换工作代码中的明确绝对目录前缀，不修改计算公式、回归变量、样本条件或FE/cluster。记录保存在PATH_CONFIGURATION_RECEIPT.json。旧脚本的源哈希/mtime检查、完成标记和一次运行保护仍然保留，遇到拒绝必须解释并另行确认，不得删除标记或绕过断言。

注意：文件路径准备完成不代表所有历史脚本的生命周期、缓存与版本自检已经移植完成。不得直接运行整个`launch.py`或`run_all`；哪些阶段仍需处理见RUN_ORDER.md、MISSING_INPUTS.md。

## 五、验证等级与下一步

本轮完成了版本和归档校验、辅助脚本语法检查，以及22个真实原始来源的只读路径/哈希检查。**没有执行materialize或任何研究程序，没有做新机端到端数值复现。** 因此不能把本补充称为“已经一键从头复现成功”。

原Gao控制表与黄文年度股东来源此前的上传缺口已补归档。ST完整状态历史、早期P0207历史/回溯解释、作者名单及模型定义歧义仍不是补传文件能自动解决的问题。继续先读AI_HANDOFF_PROMPT.md，先核验，取得新授权后再开展任何变量构造或回归。

仓库必须保持Private。数据访问、CSMAR许可、参考论文的各自权利边界继续适用。
