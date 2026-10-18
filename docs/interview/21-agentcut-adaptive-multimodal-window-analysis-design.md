# AgentCut 自适应多模态分窗分析设计

日期：2026-10-17
版本：v1
状态：设计已确认；尚未实施，不代表当前代码已具备本文能力。
范围：稳定“视频分析 -> 脚本生成”主链路，重点解决长视频视觉输入过重、ASR/VLM 时间对齐、分批并发和证据汇总问题。

## 1. 文档关系与设计边界

本文承接并细化以下设计：

- `15-agentcut-timeline-script-design.md`：七列脚本、事实与建议分离、时间和原声可追溯。
- `17-agentcut-integrated-workbench-design.md`：真实视频到脚本优先，模型选 ID、程序负责时间与门禁。
- `18-agentcut-boundary-questions.md`：部分失败、资源耗尽、并发和成本边界。
- `19-agentcut-long-video-and-api-timeout-design.md`：工程分块不等于语义单元，有界并发、共享预算和晚到结果拒绝。
- `20-agentcut-development-plan.md`：实施批次、依赖关系和验收顺序。

本文不替代上述文档。它冻结“多模态分窗分析”的专门设计，并为后续 B1 契约和 B2 分析链路实施提供依据。

本文不包含：

- 七列脚本 UI、素材库推荐或渲染重构。
- 复杂电影剧情线、多素材叙事或人物关系长期记忆。
- MQ、分布式调度或全链路 exactly-once。
- 宣称固定参数适用于所有模型、账户限流和视频类型。

## 2. 业务目标

目标链路：

> 用户内容类型/自动识别 -> 自适应时间窗口 -> ASR 与 VLM 独立分片分析 -> 全局时间轴融合 -> 窗口级多模态证据 -> 全片主题与章节分析 -> 脚本 Agent -> QA 与确定性门禁。

核心要求：

1. 长视频不能把全部帧一次提交给 VLM。
2. ASR 和 VLM 可以独立切分，但必须映射到同一原视频全局时间轴。
3. 每条视觉和语音结论必须可追溯到原始区间或帧时间，不再只依赖数组下标。
4. 用户选择的内容类型保持不变；自动识别只校正技术节奏、窗口和采样参数。
5. 分批失败不能默认拖垮整片，也不能把缺失分析伪装成完整成功。
6. 最终脚本 Agent 同时获得全片摘要和细粒度时间证据，不能只消费多层摘要。

## 3. 当前实现与主要差距

当前源码已具备：

- PySceneDetect 镜头检测。
- 按场景中点抽取关键帧。
- VAD + 不超过 30 秒音频块的 ASR，以及块级全局 `start/end`。
- Scene、TranscriptSegment、AnalysisReport 和 PlanAgent。
- LangGraph 中抽帧与 ASR 两个分支的粗粒度并行。
- 模型超时、有限重试、来源标记、任务终态保护和 `NEEDS_REVIEW` 的部分基础。

当前不具备：

- 45～75 秒的场景边界自适应窗口。
- 按视频类型和实际镜头密度调整帧预算。
- 窗口内多批 VLM、有界并发和批次结果合并。
- 独立 `FrameObservation` 及显式帧时间戳。
- ASR/VLM 基于全局时间交集的融合结构。
- 窗口级覆盖率、失败范围和证据完整性度量。
- 从窗口结果到全片主题，再到脚本决策的分层聚合。

现有 `scene_detect.py` 在场景超预算时直接采样场景列表，可能导致未采样源区间从后续视觉分析中消失；新设计要求“完整源索引”和“视觉采样预算”分离。

## 4. 术语

| 术语 | 定义 |
|---|---|
| Shot/镜头 | PySceneDetect 检出的连续镜头区间；一次切换通常产生一个新镜头 |
| Semantic Scene/语义场景 | 一个具有相对完整语义的内容区间，可包含多个镜头 |
| AnalysisWindow/分析窗口 | 控制一次局部分析规模的工程窗口，不直接等于镜头或语义场景 |
| FrameObservation/帧观察 | VLM 对指定帧的结构化视觉结论，带全局时间戳 |
| TranscriptSegment/转写片段 | ASR 输出的语音文本与全局时间区间 |
| WindowAnalysis/窗口分析 | 一个分析窗口中的视觉、语音、主题和覆盖信息 |
| GlobalAnalysis/全片分析 | 跨窗口聚合的主题、章节、论点、亮点、冗余和依赖 |

镜头数量不等于语义不同场景数量。快剪视频可能频繁切回同一人物或相似画面，因此必须经过视觉去重和时间覆盖选择，不能简单地“每镜头一帧全部调用 VLM”。

## 5. 参数依据与当前实测

### 5.1 行业区间

公开资料显示，不同视频类型的画面变化密度差异明显：

| 类型 | 常见镜头/画面变化密度 |
|---|---:|
| 慢节奏纪录片、访谈 | 2～8 次/分钟 |
| 教程、知识口播 | 6～15 次/分钟 |
| 普通口播、Vlog | 10～30 次/分钟 |
| 快节奏 YouTube | 25～45 次/分钟 |
| Shorts、TikTok、广告 | 30～60+ 次/分钟 |

这些数据只作为先验，不作为硬编码真值。同一类型内部也可能相差数倍。

### 5.2 项目素材镜头密度

使用当前 PySceneDetect 检测参数并取消 24 场景上限后，已有素材得到：

| 素材 | 时长 | 原始镜头数 | 镜头/分钟 |
|---|---:|---:|---:|
| `test_video.mp4` | 60.00 秒 | 1 | 1.00 |
| `test1min.mp4` | 96.33 秒 | 29 | 18.06 |
| `xunmeng.mp4` | 180.35 秒 | 124 | 41.25 |

结论：固定每分钟 8～12 帧不足以覆盖所有类型，但高密度素材也不能把全部镜头无差别提交给模型。

### 5.3 SiliconFlow VLM 实测

模型：`Qwen/Qwen3-VL-8B-Instruct`。素材：`xunmeng.mp4` 真实场景帧。

短输出提示词、高细节模式：

| 图片数 | 结果 | 耗时 |
|---:|---|---:|
| 1 | 成功 | 12.86 秒 |
| 2 | 成功 | 18.49 秒 |
| 4 | 成功 | 21.34 秒 |
| 6 | 成功 | 26.82 秒 |
| 8 | 成功 | 31.25 秒 |
| 10 | 成功 | 35.60 秒 |
| 12 | 成功 | 50.24 秒 |
| 16 | 成功 | 80.07 秒 |
| 22 | 成功但接近期限 | 102.68 秒 |

当前业务提示词：

| 图片数/模式 | 结果 | 耗时 |
|---|---|---:|
| 6 张，高细节，`max_tokens=16384` | 成功 | 70.39 秒 |
| 8 张，高细节，`max_tokens=16384` | 120 秒超时 | 120.08 秒 |
| 6 张，低细节，局部提示词 | 成功 | 32.08 秒 |
| 8 张，低细节，局部提示词 | 成功 | 43.50 秒 |

6 张/批的并发测试：

| 并发度 | 结果 | 总耗时 |
|---:|---|---:|
| 1 | 全部成功 | 24.59 秒 |
| 2 | 全部成功 | 34.35 秒 |
| 3 | 全部成功 | 29.34 秒 |

本组没有出现 429/503/504，但样本量不足以证明并发 3 长期安全。初始生产策略仍采用单批最多 6 张、VLM 并发 2、`detail=low`。

### 5.4 资料来源与结论边界

行业节奏参考：

- YouTube 纪录片频道画面变化统计：<https://umbrellacreators.com/blog/youtube-video-cut-pacing-data>
- 不同视频类型的 cuts-per-minute 区间：<https://cutscore.io/blog/cuts-per-minute>
- 广告镜头密度研究：<https://arxiv.org/html/2510.26569v1>

SiliconFlow 官方资料：

- 文档入口：<https://api-docs.siliconflow.cn/docs/userguide/introduction>
- 视觉能力与多模态输入：<https://docs.siliconflow.cn/docs/userguide/capabilities/vision>
- 限流规则：<https://docs.siliconflow.cn/cn/userguide/rate-limits/rate-limit-and-upgradation>
- API 错误码：<https://docs.siliconflow.cn/docs/userguide/faqs/error-code>

官方资料确认支持多图片 URL/Base64 输入，并说明上下文、视觉 token 和 RPM/TPM 等限制，但没有给出当前 Qwen3-VL 固定的“单次最多图片数”。因此本文的 6 张/批是 AgentCut 在当前模型、业务提示词、图片和超时配置下的稳定起点，不是模型或平台的官方硬上限。

## 6. 总体架构

```text
视频元数据与完整镜头检测
        ↓
AnalysisProfileResolver
用户内容类型 + 自动技术节奏识别
        ↓
WindowPlanner
45～75 秒场景/静音边界自适应窗口
        ↓
┌────────────────────┬────────────────────┐
│ ASR 分析轨道        │ VLM 分析轨道        │
│ VAD 独立分片        │ 窗口候选帧生成       │
│ 每块 ≤30 秒         │ 去重/覆盖/预算选择    │
│ 全局时间戳          │ 每批 ≤6 张，有界并发  │
└────────────────────┴────────────────────┘
        ↓
TemporalFusion
按全局时间交集融合 ASR 与 VLM
        ↓
WindowAnalysis[]
        ↓
GlobalAnalysisAgent
主题、章节、论点、亮点、冗余、依赖
        ↓
MaterialIndex / Script Evidence
        ↓
PlanAgent / DirectorDecision
        ↓
QA + DeterministicValidator
```

ASR 与 VLM 独立分片、并行执行。两条轨道不要求拥有相同边界，只要求使用同一原视频全局时间坐标。

## 7. 用户类型与自动识别

### 7.1 双层策略

```text
用户内容类型（业务意图，手动选择时不被覆盖）
        +
系统技术节奏（根据素材自动检测）
        ↓
最终窗口、帧预算和提示词策略
```

第一阶段内容类型：

- `AUTO`
- `TUTORIAL_INTERVIEW`
- `VLOG_DOCUMENTARY`
- `FAST_SHORT_VIDEO`

用户手动选择内容类型后，系统不能把教程改判为 Vlog；自动层只调整技术参数和节奏标签。用户选择 `AUTO` 时，系统才同时推断内容类型。

### 7.2 自动识别指标

首版使用确定性指标，不新增一次分类模型调用：

- 镜头数/分钟和平均镜头时长。
- 相似帧比例和去重后有效镜头数。
- ASR 有声占比。
- 语速和停顿比例。
- 画面变化强度。

输出至少包含：

```json
{
  "requestedType": "TUTORIAL_INTERVIEW",
  "effectiveType": "TUTORIAL_INTERVIEW",
  "detectedPace": "FAST",
  "shotCountPerMinute": 35.0,
  "novelShotCountPerMinute": 17.0,
  "confidence": 0.82,
  "adjustmentReason": "实际镜头密度高于类型默认范围"
}
```

## 8. 自适应窗口

### 8.1 规划规则

- 目标窗口长度：60 秒。
- 搜索范围：45～75 秒。
- 边界优先级：可靠静音边界 > 镜头边界 > 60 秒硬切。
- 相邻窗口可携带约 1 秒上下文重叠，用于避免切断语句或动作。
- 窗口主区间必须无遗漏覆盖全片。
- 重叠上下文不重复计入覆盖率和最终证据。
- 所有窗口记录原视频 hash、窗口 ID、全局 `start/end` 和规划版本。

内容类型可校正窗口：

| 内容类型 | 初始窗口 |
|---|---|
| 教程/访谈 | 目标 60 秒，45～75 秒 |
| Vlog/纪录 | 目标 50～60 秒，45～75 秒 |
| 快节奏短视频 | 目标 30～45 秒，必要时仍受全局调用预算限制 |
| 自动 | 根据检测节奏选择上述范围 |

固定时长是工程预算，不是语义单元。最终脚本只能引用完整、合法的索引单元。

### 8.2 完整覆盖

镜头检测必须保留完整镜头列表。帧预算只决定哪些镜头获得昂贵 VLM 观察，不得删除未采样镜头的源区间或长期 ID。

窗口规划必须满足：

```text
第一个主区间从 0 开始
相邻主区间首尾连续
最后一个主区间结束于视频 duration
所有区间合法且单调
```

## 9. 自适应抽帧与 VLM 分批

### 9.1 候选帧生成

每个窗口：

1. 为窗口内每个完整镜头生成候选关键帧，默认使用镜头中点。
2. 对较长镜头按时间补充候选帧，避免一个 60 秒单镜头只有一张图。
3. 使用感知哈希进行低成本相似帧去重。
4. 保证窗口首、中、尾和主要时间区域均有覆盖。
5. 根据去重后有效镜头密度选择最终帧预算。

第一阶段不引入视觉 embedding 服务。只有感知哈希在真实素材上持续漏掉语义相近但像素差异大的重复画面时，再评审 embedding 聚类。

### 9.2 初始帧预算

| 去重后有效镜头/分钟 | 提交 VLM 的帧数 |
|---|---:|
| 1～8，低密度 | 6～8 |
| 9～20，中密度 | 10～12 |
| 21～35，高密度 | 14～18 |
| 36+，超高密度 | 18～24 |

帧数按实际窗口时长等比例调整，并受任务调用预算限制。少于目标帧时不重复制造相同图片凑数。

### 9.3 API 分批

- 单次最多 6 张图片。
- `detail=low`。
- 每批提示词只包含本批帧、所属窗口和相关转写，不重复要求生成整片全部场景。
- 默认 VLM 并发 2。
- 每批输出显式携带 `frameId` 和全局 `timestamp`。
- 单批超时后拆成最多 3 张/批，剩余预算内重试一次。
- 429 遵守服务端等待信息并指数退避；503/504 和读取超时按临时错误处理。
- 不把业务无候选、JSON 语义错误和认证/余额错误当网络错误无限重试。

## 10. ASR 独立分片

ASR 保持独立 VAD 轨道：

- 完整视频提取音轨。
- VAD 检测语音区间。
- 相邻语音合并，并切成不超过 30 秒的音频块。
- 每块保留原视频全局 `start/end`。
- 单块失败不丢弃其他成功块。
- 块边缘重叠文本在合并时去重。
- 当前云端块级文本不能伪装成句级精确时间。

ASR 块可以跨越视觉窗口。融合时保留 ASR 原始记录，通过引用关联多个窗口，不复制并修改其原始时间。

ASR 并发初始值为 2；是否提升到 3 由真实 ASR 限流、耗时和失败率测试决定。

## 11. 时间轴数据契约

### 11.1 FrameObservation

```json
{
  "frameId": "frame_w005_003",
  "windowId": "window_005",
  "sceneId": "scene_000087",
  "timestampMs": 318600,
  "description": "人物展示产品操作界面",
  "tags": ["人物", "软件操作"],
  "importance": 0.82,
  "source": {
    "mode": "REAL",
    "provider": "siliconflow",
    "model": "Qwen/Qwen3-VL-8B-Instruct"
  }
}
```

### 11.2 TranscriptSegment

```json
{
  "transcriptId": "asr_000021",
  "startMs": 315200,
  "endMs": 322800,
  "text": "接下来演示具体操作步骤",
  "timingQuality": "COARSE_BLOCK",
  "source": {
    "mode": "REAL",
    "provider": "siliconflow",
    "model": "configured-asr-model"
  }
}
```

### 11.3 AnalysisWindow

```json
{
  "windowId": "window_005",
  "startMs": 300000,
  "endMs": 361400,
  "contextStartMs": 299000,
  "contextEndMs": 362400,
  "sceneIds": ["scene_000080", "scene_000081"],
  "selectedFrameIds": ["frame_w005_001", "frame_w005_002"],
  "profileVersion": "1.0",
  "plannerVersion": "1.0"
}
```

### 11.4 WindowAnalysis

```json
{
  "windowId": "window_005",
  "startMs": 300000,
  "endMs": 361400,
  "frameObservationRefs": ["frame_w005_001", "frame_w005_002"],
  "transcriptRefs": ["asr_000020", "asr_000021"],
  "summary": "演示具体操作步骤并解释注意事项",
  "topics": ["操作演示", "注意事项"],
  "events": [],
  "coverage": {
    "selectedFrames": 12,
    "successfulFrames": 12,
    "asrOverlapMs": 41800,
    "visualComplete": true,
    "audioComplete": true
  },
  "provenance": {}
}
```

时间字段跨端统一使用整数毫秒、左闭右开 `[startMs,endMs)`。模型不能自由修改帧时间、ASR 时间或源区间。

## 12. TemporalFusion

融合规则：

1. `FrameObservation.timestampMs` 落在 ASR `[startMs,endMs)` 内时直接关联。
2. 没有直接相交时，可关联时间距离最近且在配置阈值内的转写，但必须标记为邻近关联。
3. ASR 跨窗口时按时间交集引用到多个窗口，原记录保持唯一。
4. 窗口重叠帧按 `frameId`、时间戳和感知哈希去重。
5. 局部 sceneIndex 在进入融合前转换为稳定的全局 `sceneId`。
6. VLM 输出中未知 frameId、越界时间或重复冲突证据必须拒绝。
7. 视觉与语音矛盾时同时保留证据并标记风险，不强行覆盖其中一方。

融合不是把 VLM 和 ASR 文本简单拼接。窗口总结必须引用输入证据 ID，方便脚本 QA 回查。

## 13. 全片分析与脚本 Agent

脚本 Agent 接收两层信息：

- `WindowAnalysis[]`：保留细粒度时间证据和覆盖情况。
- `GlobalAnalysis`：跨窗口主题、章节、论点、亮点、冗余和依赖摘要。

GlobalAnalysisAgent 的职责：

1. 按全局时间顺序读取窗口结果。
2. 合并跨窗口的同一主题和连续事件。
3. 识别跨窗口定义、指代、条件、因果和问答依赖。
4. 生成主题候选、章节和脚本候选证据。
5. 不直接生成自由源时间；最终仍引用 MaterialIndex 的合法单元 ID。

PlanAgent/DirectorDecision 必须能够回查：

```text
script row
→ source unit
→ transcript/frame evidence
→ window
→ original global timestamp
```

多层摘要用于降低全局上下文规模，不取代原始证据。

## 14. 并发、预算和调用状态

30 个分析窗口表示 30 个待执行单元，不表示同时发起 30 个 API 请求。

初始并发：

| 资源 | 并发 |
|---|---:|
| 视频解码/抽帧 | 1～2 |
| ASR API | 2 |
| VLM API | 2 |
| 全片 LLM/脚本/QA | 1 |

每个任务必须设置：

- 总调用次数预算。
- ASR/VLM/LLM 分阶段预算。
- 单次调用总期限。
- 阶段总期限。
- 任务总期限。
- 真实在途调用计数。

SDK、HTTP 和业务层重试统一计算，不能叠加成不可控次数。调用超时后仍可能在服务商执行，本地槽位和晚到结果必须继续跟踪，不能立即当作完全释放。

每批记录：

- windowId/batchId/callId。
- runId/attempt/inputHash。
- 图片数、输入模式、耗时。
- HTTP/SDK 错误分类。
- usage、费用或未知状态。
- 结果 hash 和是否被当前任务接受。

## 15. 失败、降级和质量状态

| 情况 | 行为 |
|---|---|
| 单个 VLM 批次超时 | 拆成最多 3 张/批，在剩余预算内重试一次 |
| 单个窗口部分帧失败 | 保留成功帧，记录视觉覆盖率 |
| VLM 全窗口失败、ASR 可信 | 允许 ASR-only 窗口，标记视觉未验证 |
| ASR 块失败、视觉可信 | 保留视觉结果，标记语音缺失范围 |
| 关键窗口两种证据都缺失 | 不生成无依据结论，任务至少 NEEDS_REVIEW |
| 认证、余额、参数错误 | 立即失败，不自动循环重试 |
| 预算耗尽 | 有硬合格结果则 NEEDS_REVIEW，无合格结果则 FAILED |
| 晚到批次结果 | runId/attempt/inputHash 不匹配时拒绝覆盖 |

初始质量门槛：

- 主窗口时间覆盖率：100%。
- 时间戳合法率：100%。
- 选中帧 VLM 成功率目标：不低于 90%。
- 有语音区间 ASR 成功覆盖率目标：不低于 95%。
- 每个有效窗口至少有一种真实分析证据。
- 缺失窗口不超过 10% 且非关键章节：可生成草稿并进入 NEEDS_REVIEW。
- 缺失超过 20% 或关键章节证据缺失：FAILED。
- 10%～20% 之间根据关键区间覆盖和 QA 风险决定 NEEDS_REVIEW 或 FAILED。

比例只是初始验收规则，需要通过真实素材校准。任何比例都不能覆盖非法时间、伪造证据或关键内容缺失。

执行任务状态和脚本质量在逻辑上分离。当前 B0.6 兼容实现可使用终态 `NEEDS_REVIEW`；B1 契约应进一步明确 executionStatus、analysisOutcome 和 reviewStatus 的映射。

## 16. 配置建议

初始配置项：

```text
AGENTCUT_WINDOW_TARGET_SECONDS=60
AGENTCUT_WINDOW_MIN_SECONDS=45
AGENTCUT_WINDOW_MAX_SECONDS=75
AGENTCUT_WINDOW_CONTEXT_OVERLAP_SECONDS=1

AGENTCUT_VLM_MAX_IMAGES_PER_BATCH=6
AGENTCUT_VLM_CONCURRENCY=2
AGENTCUT_VLM_IMAGE_DETAIL=low
AGENTCUT_VLM_BATCH_MAX_RETRIES=1

AGENTCUT_ASR_MAX_CHUNK_SECONDS=30
AGENTCUT_ASR_CONCURRENCY=2

AGENTCUT_FRAME_BUDGET_LOW=8
AGENTCUT_FRAME_BUDGET_MEDIUM=12
AGENTCUT_FRAME_BUDGET_HIGH=18
AGENTCUT_FRAME_BUDGET_MAX=24
```

敏感 API Key 和实际模型配置继续留在本地环境，不提交 Git。配置值必须在任务输入快照或分析 manifest 中记录，确保结果可复现。

## 17. 测试与验收

### 17.1 确定性测试

- 自适应窗口完整覆盖时间轴。
- 边界优先级和 45～75 秒约束。
- 最后一段短窗口和无镜头/无静音降级。
- 全局时间戳合法、单调、不越界。
- ASR 跨窗口引用和时间交集融合。
- 重叠窗口帧去重。
- 用户类型不被自动层覆盖。
- 镜头密度与帧预算映射。
- VLM 未知 frameId、局部索引漂移和重复结果拒绝。

### 17.2 并发和故障测试

- VLM 并发 1/2/3 对照。
- ASR 与 VLM 同时执行时的资源上限。
- 429、503、504、连接失败和读取超时。
- 6 张超时拆成 3 张后的结果合并。
- 单窗口失败不取消其他窗口。
- 任务终态拒绝迟到 progress/completed。
- 超时调用仍在执行时不无限补充新调用。

### 17.3 真实素材

| 素材 | 目的 |
|---|---|
| `test_video.mp4` | 低镜头密度、无明显语音或弱语音 |
| `test1min.mp4` | 中镜头密度 |
| `xunmeng.mp4` | 高镜头密度、真实 ASR/VLM |
| 10～30 分钟授权素材 | 长视频窗口调度、成本、覆盖和全片聚合 |

完整验收链路：

```text
类型选择/自动识别
→ 自适应分窗
→ ASR/VLM 并行
→ 时间轴融合
→ 全片分析
→ 脚本生成
→ QA
→ Validator
```

验收报告必须区分：

- 机制测试与真实效果。
- 模拟、真实、局部降级和失败。
- 首次成功、重试成功、预算耗尽。
- 完整覆盖与部分覆盖。
- API 耗时、调用数、usage/费用和未知费用。

## 18. 实施边界与演进顺序

本设计不作为 B10 才开始的孤立“长视频扩展”。因为完整时间索引、显式证据时间和 VLM 分批也是当前短视频稳定生成脚本的基础，应拆入：

1. B0.7：用现有素材验证 VLM 批次、并发和完整“分析 -> 脚本”链路，形成参数基线。
2. B1：冻结 Profile、AnalysisWindow、FrameObservation、WindowAnalysis、GlobalAnalysis 和覆盖/来源契约。
3. B2a-1：实现完整镜头索引、自适应窗口、抽帧、分批 VLM、独立 ASR 和时间融合。
4. B2a-2：基于融合证据生成 MaterialIndex 和规则七列脚本。
5. B2b：导演 ID 决策、全片证据 QA 和统一门禁。
6. B10：生产级长视频缓存、块级产物复用、失败重做、持久恢复、公平调度和电影剧情线。

这样既不把核心分析能力推迟到 B10，也不在当前 B0.7 一次完成所有契约重构。

## 19. 已确认决策

1. 稳定优先。
2. 场景边界自适应窗口，目标约 60 秒，在 45～75 秒寻找镜头/静音边界。
3. 场景优先、均匀补帧，并按真实镜头密度动态调整。
4. 用户内容类型 + 自动技术节奏双层策略。
5. 用户手动选择的内容类型保持不变，自动层只校正参数。
6. ASR 独立 VAD 分片、VLM 自适应窗口、全局时间轴融合。
7. 单次 VLM 最多 6 张、低细节、默认并发 2。
8. 最终脚本 Agent 同时消费窗口细粒度证据和全片摘要。
9. 部分失败可降级，但必须显示覆盖、来源和缺失范围。

## 20. 成果边界

当前可以表述：

> 已完成长视频多模态分窗、类型自适应采样、ASR/VLM 全局时间融合和有界并发的设计，并使用真实项目素材与 SiliconFlow VLM 做了初步参数实验。

尚不能表述：

- 已支持 30 分钟长视频稳定分析。
- 已实现窗口级并发、时间融合或自动类型识别。
- 已证明脚本质量提升。
- 并发 2 或帧预算是生产最优参数。
- 已具备断点恢复、缓存复用或分布式调度。

只有完成对应批次、真实长视频验收和人工脚本质量评测后，才能把设计结论改写为实现成果。
