# 接收、文件地图与复现边界

## 只读验收（本轮唯一运行入口）

在github_repo目录执行 `python3 tools/verify_package.py`。只用Python标准库，校验manifest.json中的字节数与SHA256；若相邻私下包存在，还校验其冻结文件。不会调用Stata、计算SYN、拟合倾向得分或回归。

校验通过只代表包内文件完整，不代表识别成立，也不代表已经在新机器重跑。新AI先读文档就能接手；数据级复核要拿到私下包。**完整历史不是一键可移植流水线。** 不提供未经测试的run_all假装可以自动复现全部历次探索。

## 关键文件和程序地图

下表私下路径相对于private_data_DO_NOT_UPLOAD/workspace/。每个文件实际位置、原路径与SHA256见私下SOURCE_MANIFEST.tsv；dependency_path_map.tsv逐个对应原机器路径。阅读副本在公开docs/source_reports；原件不改。

|用途|私下目录/关键文件|程序/入口（仅供获授权后审查）|公开结果|
|---|---|---|---|
|G1冻结输入|four_cohort_G1_final_fixed_rerun_20261103_work/outputs/input_snapshot/latest_G1_analysis_original.dta|同目录run_once.do|results/G1_frozen|
|G1静态/动态代数审计|four_cohort_G1_estimand_audit_20261103_work/outputs|该目录原审计程序与日志|results/G1_estimand|
|周历修复后H8数据|huang_week_calendar_repair_20261103/fixed_rerun/outputs/fixed_analysis.dta|repair.py及fixed_rerun原程序；不要重复全库构造|results/calendar_repair|
|H8过渡期模型|huang_transition_static_H8_20261104/outputs/*.ster|run_transition.do；原样本old_H8_sample==1|results/H8_transition|
|DR已构造输入|huang_DR_DID_2008_complete_20261109/outputs/dr_analysis_wide.dta|run_fixed.do；已完成12项估计，不再启动launch.py|results/DR_DID|
|最新来源审计|huang_H8_DR_source_audit_20261109/outputs|audit.py、extract_existing.do、complete_report.py|results/latest_source_audit|
|基线和任免证据|controls_2008_*；duality_2008_*|现有台账、逐源哈希；不填缺失|私下版|
|历史Gao/政策映射|../legacy_20261028/private_data与github_repo|旧代码与来源表；不是当前默认入口|results/history_20261028|

## 移机时必须先处理

原脚本有作者机器绝对路径、相邻工作目录、一次运行保护标记、源mtime/哈希校验，不能直接执行archive整目录。公开代码保留原路径以便审计；private source map定位副本。迁移时在新的工作副本中配置路径，不能改原始快照或以删除完成标记来强行续跑。某些旧源码引用未全部打包的外部历史输入，应先按inventory核对，缺源就停止，不猜路径。

无需重建数据就可核对冻结模型：G1分析DTA、H8 fixed_analysis.dta、DR dr_analysis_wide.dta及全部对应.ster/CSV已包含。但本轮没有授权实际回归复现；新机模型重跑必须另经批准并先核对命令、样本与软件环境。

## 环境与资源

原运行环境macOS、StataMP，Python pandas/numpy；drdid版本1.91，原Stata及ado程序版本证据在私下日志/环境清单。本次交接并未统一锁定全项目软件环境，不虚称所有版本完全固定。常用reghdfe/ftools、drdid依赖应以随包环境清单和原日志为准。已包含drdid源副本仅作有权限私下核验，不新增第三方公开许可。

低内存：单进程，OPENBLAS_NUM_THREADS=1、OMP_NUM_THREADS=1；XLSX按实际行流式读取，DTA按列/块读取。不要相信Excel虚高metadata列数。最新来源审计峰值约148.3MiB；DR估计峰值约26MiB，仅是这些阶段，不是整库重建要求。全历史重建时间/峰值没有经统一新机测量。

## 验证等级

- 文件复制：逐文件源—副本SHA256比对；最新审计277个保护源核对。
- 本轮回归：0；SYN重算：0；源数据修改：0。
- 本轮跨机器端到端估计复现：未运行，不能报PASS。
- 当前未决：ST历史、行业回溯、未取得作者名单/实现、研究期与开题衔接。
