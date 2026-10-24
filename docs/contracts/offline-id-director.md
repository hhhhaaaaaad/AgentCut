# 素材索引与 ID 导演离线链路

日期：2026-10-23。状态：已实现最小构建器、规则基线、受控 ID 选择和脚本编译。
这批继续推进 Agent 能力，音轨/ASR 服务商适配保持暂停。

2026-10-24：新增独立的 [语义 QA 与有限修订](offline-script-review.md) 包装流程。
本页 CLI 仍描述前置的未评审草稿生成阶段。

## 数据流

```text
完整 SourceIndex + 已有转写/观察证据 + B1 输入快照
  → MaterialIndexV1
  → 规则召回 / 注入的 ID 导演
  → DirectorDecisionV1
  → 确定性编译 + 上下文校验
  → EditingScriptV1（NEEDS_REVIEW）或 NO_CANDIDATE
```

实现入口：`app/analysis/material_index.py`、`script_compiler.py`、
`offline_id_director.py`、`app/agents/id_director_agent.py`。
沿用 B1 的索引、决策、脚本与输入契约，没有修改 Plan 1.0 或现有任务端点。

## 素材索引

- `MaterialEvidence` 是独立、可保存的规范化证据快照。它的内容 hash 形成索引 `analysisRef`，不是把不完整旧报告宣称为完整多模态报告。
- 全部源场景从 `SourceIndex` 投影保留，不受候选或模型提示词预算影响。
- 每条非重叠转写生成一个完整 `SPEECH` 单元，保留原文、原视频全局整数毫秒和原有精度；跨镜头转写不会被镜头边界截断。
- 转写以外的源区间按场景切成 `VISUAL_ONLY` 单元。没有音频证据时保持 `UNAVAILABLE`，不把“没有转写”当作静音或 `NO_SPEECH`。
- 相互重叠的转写簇保留全部原始记录，但整个重叠簇不进入可选择单元；记录 `OVERLAPPING_TRANSCRIPTS` 范围。其他单元继续可用。全部源区间均不可选择时显式返回 `NO_CANDIDATE`。
- 可传入基于原始 transcriptId 的 REQUIRED/REVIEW 依赖。未知、自引用、重复声明或指向已排除重叠记录的依赖会拒绝输入，不静默丢失声明。
- unitId 由素材、种类、源区间和完整转写记录生成，独立于数组下标、观察帧数量和索引版本。内容变化会改变相应 ID；完整 indexHash 还绑定证据与依赖。

`selectableCoverageMs` 只是可选择单元的时间并集长度，不代表真实 ASR/VLM 分析覆盖率。
`INDEXED` 表示证据可表示为合法索引，也不等于素材已完整理解。
读入 `MaterialBuild` 时会从保存的源索引和证据重新推导结果，拒绝改写单元后重新封 hash 的伪造输出。

资源界限：最多 10,000 条转写、10,000 条观察、10,000 条依赖、20,000 个单元；超限明确失败。
这些是离线资源保护，不是 30 分钟生产链路验收结论。

## 规则基线与 ID 导演

规则基线使用主题的英文词/中文词组与双字片段做关键词召回，递归补齐已声明的 REQUIRED 依赖，
按相关性与源顺序进行有限贪心选择。整体单元及其依赖必须能装入硬时长上限。
输出始终保持原序、原速、硬切；期望时长是偏好，不用加速、截短转写或补编内容凑时长。
关键词召回不代表语义理解，搜索没有命中/装不下也不代表数学不可行。

`IDDirectorAgent` 只接受显式注入的 `invoke(prompt)` 适配器及 `REAL`/`SIMULATED` 来源；
不自动读取配置或构造模型客户端。模型只输出 `rows`：合法单元 ID、作用、理由与人工包装建议。
索引引用、inputHash、decisionId、原话和全部时间由程序提供。
空 rows 表示模型不选择，不会变成空的 B1 决策或脚本。

默认最多三轮；未知 ID、重复/重排、非连续合行、缺 REQUIRED 依赖、超时长及额外字段均拒绝。
失败后使用硬合格规则基线；没有基线时返回 `NO_CANDIDATE`，不生成占位原话。
每轮记录状态和耗时，原始模型错误文本不进入结果。

默认模型预算为 128 个候选、120,000 提示词字符、40,000 响应字符、120 秒启动预算。
超容量不截断源索引或静默裁减提示词候选，改用规则基线。
同步适配器必须自己配置传输超时和重试；预算不强制中止正在执行的请求，晚到结果会被丢弃，
不能据此声称远端请求已取消。没有引入新的 SDK 重试层。

## 确定性脚本编译

程序复制完整单元的 `sourceParts` 和 `spokenQuotes`，从 0 连续累计输出时间。
画面字段只复制已有帧观察；保留来源，缺帧或非真实帧标记 `VISUAL_UNVERIFIED`。

字幕只在用户请求、来源为 REAL 且有 SENTENCE/WORD/MANUAL 整条对齐时生成，
使用删除前段之后重新累计的输出全局时间。粗块不能生成假精确字幕，而是记录
`COARSE_ALIGNMENT` / `SUBTITLE_UNAVAILABLE`。
包装只保存为 `PROPOSED`，可执行动作只有原声和合法字幕，没有媒体命令或自动渲染。

本轮没有新脚本的语义 QA 适配器，因此所有脚本都包含 `QA_UNAVAILABLE` 和
`SEMANTIC_REVIEW` 风险、`quality=null`、`reviewStatus=NEEDS_REVIEW`。
即使使用真实模型做了 ID 选择，也不能升级为 READY。
这里只验证已声明依赖；漏报的上下文依赖仍须人工/后续语义 QA 回查。

## 使用已有 AnalysisReport

保守桥接器 `evidence_from_legacy()` 接受已有报告和完整源索引：

- 校验 assetId 和时长一致，不静默重绑其他素材。
- 原样保留整条转写，统一标为 COARSE_BLOCK；旧报告没有精度字段，不能凭文本推断句内边界。
- 不把场景描述伪造为有精确时间的 FrameObservation。
- 旧报告没有独立验证的素材 hash；模拟来源保持 SIMULATED，其余标为 MIXED 并说明绑定限制。
- 保存旧报告的 `upstreamAnalysisHash`，索引自身仍引用新的规范化证据快照。

桥接不会重新解码、转写、调用 VLM 或读取视频。

## 本地复现

在 `AgentCut-ai` 下运行虚构样例，不需要模型凭证：

```bash
python -m app.analysis.offline_id_director \
  --input ../docs/contracts/offline-id-director.input.json \
  --output /private/tmp/agentcut-id-director.json \
  --bundle-output /private/tmp/agentcut-id-director.bundle.json
```

样例保留 5 个源场景、11 个可选择单元；主题选中两段原文：
源 `[500,3500)`、`[4500,7500)` → 输出 `[0,3000)`、`[3000,6000)`。
期望 8 秒，实际 6 秒；不补编剩余内容。样例证据全部为 SIMULATED。

桥接已保存的原始报告 JSON（SourceIndex 必须是独立对象）：

```bash
python -m app.analysis.offline_id_director \
  --source-index /path/source-index.json \
  --legacy-report /path/analysis-report.json \
  --submission /path/b1-submission.json \
  --output /private/tmp/agentcut-legacy-id-script.json
```

CLI 只启用规则基线；真实模型适配器必须通过代码显式注入，并单独授权真实效果验收。
可选 bundle 是供三端校验的上下文文档，`events=[]`；不是伪造成功/失败回调。
旧在线 AnalysisAgent、PlanAgent、Java 回调和编辑页目前仍使用旧协议。

## 验证与后续

输入/摘要/程序生成的 B1 bundle 由 `scripts/generate_id_director_fixture.py` 重现，漂移纳入 Python 测试。
Python 验证完整构建与错误恢复；Java 和 TypeScript 读取同一份实际编译样例，验证双时间与风险。
测试仅使用本地 stub，不代表真实模型选题效果验收。

本分支本地验收：Python 3.14 全量 432 项通过（新增 51 项），Java 17 全量 133 项通过
并完成 `mvn verify`；前端共享 85 组 B1 样例与新增程序编译样例均通过。

下一步：为新脚本增加绑定候选 hash 的语义 QA 与修订，再接入在线输入快照和结果保存。
这批完成了 B2a-2/B2b 的最小离线切片，尚未完成多模态融合、在线策略切换或生产级任务恢复。
