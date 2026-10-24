# B2a-1 第三批：独立音频轨道与 ASR 时间轴

实施日期：2026-10-23。独立离线实现，沿用 B1 原视频全局整数毫秒和左闭右开区间。

## 交付

- VadObservation：显式记录源素材、检测器版本/配置、实际检测区间、语音区间、音轨是否存在及可靠性。
- AudioPlan：按语音边界合并邻近语音、生成稳定 audio chunk ID，保存主区间与识别请求区间。
- AsrAdapter：异步块级识别接口，默认并发 2、单块期限 30 秒，无隐式重试。
- AsrChunkResult：逐块保留成功、明确无可识别语音、模拟来源或失败；缺少结果生成 MISSING_RESULT。
- AsrTrack：原始粗粒度转写、跨视觉窗口引用、语音覆盖与缺失指标、可回查的显示文本去重。
- 本地视频/PCM WAV 的 WebRTC VAD 适配器与 JSON 离线 CLI。

这些模型为 Python 离线 0.1 版本。原始转写投影使用 B1 TranscriptSegmentV1，
当前在线 AnalysisAgent/旧 transcribe 路径未迁移；不生成完整多模态 AnalysisEvidence。

## 分片和覆盖规则

VAD 输入区间必须有序、非空、不重叠，语音必须完全位于实际检测范围内。
未知区间保持 unknownRanges，不视为静音。只有来源为 REAL 的可靠观测能够生成视觉规划 SilenceCue。
完整可靠 VAD 未发现语音，或已验证源视频没有音轨，才会生成音频轨道 NO_SPEECH。
检测器不可用、失败或只完成前缀时不声称整片无语音。

默认合并不超过 1000ms 的已观测语音间隔。识别请求左右各最多 500ms 重叠，
重叠也计入单次最多 30000ms 的限制；一段不超过 30 秒的语音可直接生成一个请求。
分块不会跨过未观测间隙。语音覆盖按原始 VAD 区间的时间并集计算，重叠请求不会重复计数。
默认最多 4096 块；超限在分配块前拒绝，不输出残缺计划。视觉分窗、帧预算变化不会改变音频分片。

每块结果只提供 chunkId、assetHash、原文、来源、状态或错误，不能自由指定时间。
程序从该块 requestRange 派生全局 startMs/endMs，timingQuality 固定为 COARSE_BLOCK。
不按字符数拆句，不伪造 WORD/SENTENCE 时间。原始文本及区间保留一份，多个窗口只引用同一 transcriptId。

transcribedSpeechMs 仅统计 REAL 成功转写请求与 VAD 语音相交后的时间并集。
模拟文本继续保留，但不计入真实转写覆盖。逐窗口列出 transcriptRefs、failedChunkRefs、
已检测时间、语音时间、真实转写时间、缺失语音时间与未知时间。
VAD 检出语音但识别器声明 NO_SPEECH 时保留 VAD_ASR_DISAGREEMENT，不把空响应直接当作可靠静音。

COMPLETE / NO_SPEECH / PARTIAL / UNAVAILABLE 表示本音频阶段的覆盖和来源，不直接映射成任务终态或脚本 READY。
模拟/不可靠 VAD、未知区间、模拟 ASR、块失败或识别冲突都保留为待复核结果。

## 重叠文本和超时

相邻转写请求有时间重叠、来源模式/服务商/模型一致，且原文后缀与下一块前缀精确匹配至少八个字符时，
displayText 可去掉匹配前缀；textJoins 记录原始引用和 removedPrefix。
原始 transcripts 永远保留，显示去重不提供精确语音对齐，也不作为剪辑入出点或 MaterialIndex 原话的替代。
语义上有意重复的句子仍可能相同，后续人工复核必须可回看原文。

异步执行器保留源顺序并限制并发；某块异常不清空其余结果。
下一次显式调用可传入 existing_results，校验相同素材/分片 ID 后，仅补跑失败或缺失的块，复用成功记录与稳定引用。
这不自动重试、不覆盖原结果快照，也不声称服务重启后自动恢复任务。
超时会请求取消本地协程，返回迟到的成功也不发布；不声称已取消远端调用。
接入的适配器必须响应协程取消并在自身网络客户端设置期限，这不是不合作调用的进程级强制中止或持久恢复机制。

## 本地音频适配器

代码：AgentCut-ai/app/tools/audio_vad.py。

- 校验源文件 SHA-256，错误绑定直接拒绝。
- ffprobe 校验视频流时长与素材快照一致，并获取起始 PTS；缺失时长或不一致时不填充虚构源区间。
  FFmpeg 保留音频原始偏移，以视频流起点为时间零，按需补零/裁去负时间样本。
- 解码为 16kHz、单声道、PCM16 WAV，样本数量必须与源时间轴时长一致。
- WebRTC VAD 按 10/20/30ms 帧处理；最后不足一帧时仅为分类补零，覆盖统计仍只包含真实源时长。
- 不过滤短语音；VAD 中途失败保留已完成前缀，其余时间未知。
- 默认最多处理十分钟素材、整个本地处理期限 30 秒；这是资源限制，不是长视频生产能力验收。
- 所有中间 WAV 位于临时目录并自动清理，不保存测试媒体到仓库。

本地 CPU 检测组件单独固定在 requirements-audio.txt：
webrtcvad-wheels 2.0.14.post1。格式和帧长规则来自[维护者文档](https://github.com/daanzu/py-webrtcvad-wheels#how-to-use-it)。
该组件不下载 ASR 模型，也不调用云端识别。

## 离线复现

从 AgentCut-ai 目录，使用安装了 requirements-test.txt 的独立测试环境：

```sh
AGENTCUT_LOAD_DOTENV=false AGENTCUT_AI_SIMULATE=true AGENTCUT_VLM_API_KEY='' AGENTCUT_LLM_API_KEY='' \
  python -m app.analysis.offline_audio_track \
  --visual-plan ../docs/contracts/offline-window-planning.output.json \
  --input ../docs/contracts/offline-audio-track.input.json \
  --output /private/tmp/agentcut-offline-audio-track.json
```

手工模拟样例：46 秒语音、3 块、2 块成功/1 块失败；原始区间为 [55000,85000)、[84000,95000)，
第一份转写跨两个视觉窗口引用。全部成功文本也标记 SIMULATED，真实转写覆盖为 0，整体 PARTIAL。
审阅摘要：[offline-audio-track.summary.json](offline-audio-track.summary.json)。

本地真实 VAD 可额外安装 requirements-audio.txt，使用 --video /path/to/source.mp4，或对 WAV 源素材使用 --wav。
素材 hash 必须匹配视觉规划；--wav 仅接受 WAV 本身作为源资产，不把无来源绑定的派生 WAV 冒充原视频。
这两种入口仅检测和规划，不调用 ASR；检测到语音而缺少识别结果时会明确记录缺失块。

CI 的 Python 3.11/3.14 矩阵安装固定的测试依赖与本地 VAD 组件，自动运行全量测试。
已覆盖长语音、短语音、静音、无音轨、检测未知/局部失败、30 秒上限与重叠、跨窗引用、来源/身份拒绝、
显示去重、并发与迟到结果、持久结果篡改及离线 CLI。真实 CPU VAD 使用合成静音音频验证。
合成带偏移媒体另做本地解码验证：视频起点 2.5 秒、音频延后 0.5 秒，检测输入标记正确映射回约 0.5 秒；
该项使用测试能量标记确认时间对齐，不作为人声识别效果证明。

下一批接真实 ASR 服务商适配器的单独验收、选中彩色帧与分批 VLM，然后实现 TemporalFusion。
