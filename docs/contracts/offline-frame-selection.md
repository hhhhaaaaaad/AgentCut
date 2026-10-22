# B2a-1 第二批：窗口候选帧与 pHash 去重

实施日期：2026-10-22。此批接在完整源索引/窗口规划之后，提供独立离线选择器及本地视频解码入口。

## 已实现

- 每个主窗口与源镜头的交集生成中点候选；长镜头默认每 10 秒补充采样，并添加首、中、尾及六个时间桶的候选。
- 相同源时间只保留一个候选并合并生成原因。时间为原视频全局整数毫秒，遵守镜头和主窗口的左闭右开边界。
- frameId 绑定素材 ID/hash、sceneId、请求时间和候选算法版本，不依赖数组下标或帧数预算。请求时间与实际解码时间分别保存。
- 候选上限显式报错，不裁掉完整源索引。默认每窗最多 2048 个候选、全任务 20000 个候选。
- 纯标准库 pHash：32×32 面积均值缩放、减去均值、正交 DCT-II、左上 8×8 频域、63 个 AC 系数中位数阈值、DC 位为 0。
- 固定算法版本 agentcut-phash-dct32-area8-v1，哈希为 16 位小写十六进制。默认汉明距离阈值为 6，可配置。
- 相似组内任意两帧都须满足阈值；不通过相似关系传递合并。REAL 与 SIMULATED 样本分组隔离，失败样本不参与去重。
- 按去重后的镜头中点组密度选择 8/12/18/24 的每分钟预算，按实际窗长缩放，容量限制在 6～24 且遵守配置上限。
- 通过最多六个时间桶与相似组的匹配选择代表帧，尽量覆盖首、中、尾及主要时段；余量优先补充未代表镜头和时间距离较远的帧。
- 同一相似组最多选择一帧。独特画面不足时允许少于预算，不重复图片凑数。源镜头全部保留，并列出未获得选中帧的 sceneIds。
- 丢失/失败样本逐帧记录；一个窗口失败不清空其他窗口。输入中未知/重复 frameId、错误素材 hash、越界解码时间或未知哈希版本会被拒绝。
- 输出独立 selectedWindows，使用 B1 AnalysisWindow 并填入 selectedFrameIds；原窗口规划保持原样。
- 持久结果读取时重新计算候选、分组、选择、覆盖指标和选择 ID，拒绝篡改的引用或覆盖声明。

## 覆盖指标和限制

每窗均匀划分最多六个时间桶，记录：

| 字段 | 含义 |
|---|---|
| decodedBins | 有成功解码/声明样本的时间桶 |
| selectedBins | 实际选中帧时间戳所在的时间桶 |
| equivalentBins | 与选中帧处于同一 pHash 相似组的候选时间桶 |
| missingSelectedBins | 尚无实际选中帧的时间桶 |
| failedFrameIds | 缺少样本或明确失败的候选 |
| sceneIdsWithoutSelectedFrame | 未获得选中帧的源镜头，仍保留在完整索引中 |

这些指标统计采样点，不把单张图片扩张为一段已经理解的视频。
pHash 只反映低成本的画面相似度；均匀色图会共享零哈希，亮度/颜色或语义变化可能漏检。
equivalentBins 不表示已经完成语义分析；即使全部等价时间桶有覆盖，实际选中时间桶缺口仍显式保留。

结果状态 SELECTED / PARTIAL / UNAVAILABLE 仅描述本阶段。模拟样本、源检测不完整、
样本失败或选中时间桶缺口都会使结果保留为 PARTIAL。它们不映射为整片 AnalysisEvidence 的 COMPLETE / READY。
全局 AnalysisProfile 的 frameBudget 仍是规划时容量；本阶段每窗 budget 才反映去重后、按实际时长计算的容量。
未知源区间不计入已检测镜头密度；源检测为模拟时，密度与选择结果也明确处于待复核状态。

## 本地解码适配器

AgentCut-ai/app/tools/window_frames.py::hash_video_candidates：

1. 流式校验原文件 SHA-256 与规划素材 hash 一致。
2. ffprobe 读取首视频流的起始 PTS/time_base；FFmpeg 仅解码候选处的 32×32 灰度缩略帧。
3. 从解码 showinfo 的实际 PTS 计算相对视频流起点的全局时间。后续 FrameObservation 必须使用 decodedTimestampMs，不使用请求时间冒充解码时间。
4. 实际时间须在候选源镜头、主窗口内，且默认偏差不超过 1000ms；否则记录 UNAVAILABLE。
5. 文件/工具缺失、时间不可验证或单帧失败均明确记录，不产生假图片或假哈希。

默认单次最多解码 256 个候选、整个调用共用 10 秒超时；可配置但硬上限为 1024 帧/120 秒。
候选数超限在启动解码前报错；总时间耗尽后，其余候选标记不可用。逐帧检查源文件是否发生变化。
此入口只解码缩略图，不保存成片，也不调用应用的剪辑/渲染链路。当前没有保存供 VLM 使用的彩色图像。

## 离线复现

从 AgentCut-ai 目录执行：

```sh
AGENTCUT_LOAD_DOTENV=false AGENTCUT_AI_SIMULATE=true AGENTCUT_VLM_API_KEY='' AGENTCUT_LLM_API_KEY='' \
  .venv314/bin/python -m app.analysis.offline_frame_selection \
  --plan ../docs/contracts/offline-window-planning.output.json \
  --samples ../docs/contracts/offline-frame-selection.samples.json \
  --output /private/tmp/agentcut-frame-selection-example.json
```

样本哈希来自手工生成的灰度纹理，来源显式标记 SIMULATED；前两个时间桶故意重复。
预期 30 个候选、15 个选中帧、3 个窗口，整体状态 PARTIAL；每窗五个相似组，不补足到预算数量。
审阅摘要见 [offline-frame-selection.summary.json](offline-frame-selection.summary.json)。

实际本地视频入口：

```sh
AGENTCUT_LOAD_DOTENV=false AGENTCUT_AI_SIMULATE=true AGENTCUT_VLM_API_KEY='' AGENTCUT_LLM_API_KEY='' \
  .venv314/bin/python -m app.analysis.offline_frame_selection \
  --plan /path/to/verified-source-plan.json \
  --video /path/to/source.mp4 \
  --output /private/tmp/agentcut-selected-frames.json
```

规划文件的 assetHash 必须与视频字节一致。--samples 为带 config 和 samples 的明确来源输入；
--video 可用 --config 指定 FrameSelectionConfig JSON。两种来源互斥，CLI 不导入 app.config、不加载 .env 或模型客户端。

## 验证记录与下一步

- 本批新增 141 项测试，Python 全量 381 项通过。
- 覆盖短镜头完整保留、长镜头补帧、稳定 ID、半开时间、候选上限、实际窗长预算、低/中/高密度、
  相似关系非传递、时间桶匹配、模拟隔离、单窗失败保留、来源/时间校验及持久结果篡改。
- 现有 8 秒测试视频实测：9 个候选全部从真实 PTS 解码成功，选出 6 帧，无解码失败。
  实际选中帧覆盖 5/6 个时间桶，第 4 号桶的缺口明确保留；此次未运行源镜头检测，源检测保留 UNAVAILABLE，整体为 PARTIAL。
- 正负视频起始偏移已通过子进程替身测试，真实解码验证目前只覆盖起点为 0 的素材。

下一批接独立 VAD/ASR 轨道、选中彩色帧与分批 VLM，再实现 TemporalFusion。
当前在线 AnalysisAgent 仍使用旧链路；本批未调用模型、未迁移端点，B2a-1 的多模态融合验收尚未完成。
