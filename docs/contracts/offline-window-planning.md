# B2a-1 第一批：完整源索引与窗口规划

实施日期：2026-10-22。此批交付独立的确定性离线入口，运行服务仍使用原来的分析链路。

## 已实现

- 完整源索引独立于帧预算，保留全部检测区间，包括短于 0.4 秒的镜头和超过 24 段的素材。
- 全局整数毫秒、左闭右开区间。源索引从 0 连续覆盖至 durationMs；检测缺口补为 UNOBSERVED，并保留 UNAVAILABLE 来源。
- 索引覆盖与真实检测覆盖分别记录。全时间覆盖不表示分析完成；模拟数据的 observedCoverageMs 为 0。
- sceneId 绑定素材 ID/hash、时长、检测器版本/配置、原始区间和来源模式，不依赖数组下标、窗口或帧预算。
- 完整检测适配器 detect_source_index 校验文件 SHA-256，使用一帧最小镜头长度，不进行数量采样。缺少依赖、文件不可用或检测失败时返回显式 UNAVAILABLE；成功且无切点时才生成 NO_CUT。
- AnalysisProfile 保留用户手动类型，根据已观测镜头密度调整技术节奏和目标帧预算。AUTO 暂用配置的内容类型后备值，confidence 为 0，不声称已完成内容分类。
- 教程/访谈目标 60 秒、搜索 45～75 秒；Vlog/纪录目标 55 秒、搜索 45～75 秒；快节奏短视频目标 40 秒、搜索 30～45 秒。
- 分窗优先选择可靠 REAL 静音，再选择真实镜头边界，最后按目标时长切分。候选同级时选择最接近目标的位置，距离相同取较早位置。
- 尽量保留至少 15 秒尾窗；最终窗口可短于搜索下限。首尾上下文各 1 秒并裁到素材范围；仅主区间计入 plannedCoverageMs。
- 每窗包含全部与上下文相交的 sceneIds。selectedFrameIds 为空，表示帧选择尚未执行。
- windowId 绑定素材、源索引、完整 profile/config、规划版本、策略和时间范围。边界决策记录 SILENCE / SCENE / TARGET / TAIL_GUARD / FINAL 及证据引用。
- 持久结果读取时重新校验源索引、稳定 ID、profile、窗口范围、引用和边界决策；最多 4096 个窗口，超限不输出部分计划。

## 重要输入约定

detectedRanges 必须按源时间排序、互不重叠且位于素材内。非法区间直接拒绝；不排序修复、不合并丢失短镜头。
空列表默认表示缺少检测覆盖。仅 noCuts=true 且来源 REAL/SIMULATED 时，才明确表示完整检测未发现切点。

旧秒制区间只能通过 seconds_to_ms 显式转换：四舍五入到最近毫秒，半毫秒向上。相邻端点用同一规则。
转换后坍缩为空的区间视为非法；适配器报告检测不可用，不静默删除该镜头。时间上限遵守 B1 的 JavaScript 安全整数范围。

silenceCues 必须携带素材 hash、可靠标记和来源。只有 reliable=true 且 mode=REAL 的区间能影响边界。
切点可落在静音区间的起点、内部或结束边界。现有“无转写文本即静音”的启发式不能作为可靠 VAD 输入。
本批没有运行 VAD；真实静音证据由后续独立音频轨道提供。

未运行去重时，novelShotCountPerMinute 暂用原始镜头密度作为上界，并在 adjustmentReason 中标注。
可传入已去重的 novelSceneIds，引用必须唯一且指向真实已观测镜头。这些引用只影响节奏/预算，不删除源镜头。
检测覆盖不完整时，按全片时长计算的密度是下界，技术节奏标记为暂定。frameBudget 是按目标窗长估算的容量，尚不是每个窗口实际选中的帧数。

## 代码入口

- Python：AgentCut-ai/app/analysis/source_index.py
- 类型/策略：AgentCut-ai/app/analysis/window_planner.py
- 离线 CLI：AgentCut-ai/app/analysis/offline_planning.py
- 完整检测适配器：AgentCut-ai/app/tools/scene_detect.py::detect_source_index

SourceIndex.contract_scenes() 显式投影为 B1 Scene；窗口直接使用 B1 AnalysisWindow。
本批 offline-window-plan-0.1 是 Python 离线开发产物，尚未冻结为新的 Java/前端接口。
PLANNED 只表示索引和窗口规划完成，不应映射为 AnalysisEvidence 的 COMPLETE 或 READY。

## 复现

从 AgentCut-ai 目录执行：

```sh
AGENTCUT_LOAD_DOTENV=false AGENTCUT_AI_SIMULATE=true AGENTCUT_VLM_API_KEY='' AGENTCUT_LLM_API_KEY='' \
  .venv314/bin/python -m app.analysis.offline_planning \
  --input ../docs/contracts/offline-window-planning.input.json \
  --output /private/tmp/agentcut-offline-window-plan.json

AGENTCUT_LOAD_DOTENV=false AGENTCUT_AI_SIMULATE=true AGENTCUT_VLM_API_KEY='' AGENTCUT_LLM_API_KEY='' \
  .venv314/bin/python -m pytest -q
```

示例输入为手工模拟数据，无媒体文件、无真实检测或模型调用。
对应可审阅输出见 [offline-window-planning.output.json](offline-window-planning.output.json)：
6 段源镜头、3 个主窗口 [0,60000)、[60000,120000)、[120000,140000)，覆盖 140000ms；
detectionStatus=SIMULATED，observedCoverageMs=0，status=PLANNED。

离线 CLI 不导入 app.config 或 AI 客户端，不加载 .env。真实检测适配器不在 CLI 路径上。

## 本批验证与后续

新增 92 项离线测试，Python 全量 240 项通过。覆盖完整短镜头索引、身份绑定、缺口/模拟来源、
低中高密度、手动类型、可靠边界优先级、尾窗、半开上下文引用、全片连续覆盖、超限和篡改拒绝。
检测器通过测试替身验证参数与资源释放；当前 .venv314 未安装 PySceneDetect，未宣称已用真实素材验收。

窗口候选帧、时间覆盖选择和 pHash 去重已在[第二批实施](offline-frame-selection.md)完成独立离线入口；
下一批接独立 VAD/ASR 轨道、分批 VLM 与 TemporalFusion。
本批未迁移运行端点、执行模型调用或渲染；尚不满足 B2a-1 的完整多模态融合验收。
