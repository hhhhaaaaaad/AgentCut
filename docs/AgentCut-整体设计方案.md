# AgentCut 项目整体设计方案

> 版本：v1.0　日期：2026-08-27　状态：已定稿（待开发）

---

## 1. 项目概述

| 项 | 内容 |
|---|---|
| 定位 | 视频智能剪辑：上传 → Agent 分析 → 生成可编辑方案 → 应用方案 → 输出成片 |
| 形态 | 单仓库三个子包：`AgentCut-backend`(Java) + `AgentCut-ai`(Python) + `AgentCut-front`(React) |
| 代码路径 | `E:\java\AgentCut\` |
| 包名 | `cn.sutone.cut.*` |
| 核心设计原则 | **剪辑方案文档是单一事实来源**——Agent 生成它、人编辑它、引擎执行它、系统存档它 |
| Agent 引擎 | 仅 Python LangChain 一个；Java 侧无任何 LLM 逻辑 |

### 1.1 需求拆解

一条主流水线：

```
上传视频 → Agent分析 → 生成/编辑剪辑方案(文档) → 应用方案 → 输出成片
```

关键设计约束：

1. **方案文档是单一事实来源**：Agent 生成、人编辑、引擎执行、可存档，四者共用同一份文档。
2. **人机协同**：Agent 产出的是初稿，人可改，改完可回灌、可追溯。
3. **确定性执行**：同一份方案文档，任何时候执行结果一致（可回放）。
4. **长任务**：视频分析/剪辑是分钟级任务，必须异步 + 可观测进度。
5. **单任务处理、无长期记忆**：每次分析任务自包含、无状态，不建记忆系统、不跨任务留存用户偏好；用户意图（竖屏/时长/字幕等）通过单次任务入参传入。

### 1.2 核心概念澄清：Agent 不剪视频，只产出方案

三个角色严格分离：

| 角色 | 职责 | 产物 |
|---|---|---|
| **Agent**（大脑） | 分析视频，决定剪哪、怎么剪 | 剪辑方案 JSON |
| **剪辑方案**（蓝图） | 一份结构化指令清单（timeline + operations） | 既是给人看的，也是给机器执行的 |
| **FFmpeg**（手） | 按方案实际裁剪/变速/加字幕/转码 | 成片 |

- Agent 产出的方案**不是视频、不是代码**，而是"机器可执行、人可编辑"的指令清单。
- 真正的像素级操作由 FFmpeg 确定性执行（`plan → FFmpeg` 见第 9 节）。

**两种应用模式（当前设计都支持）**：

| 模式 | 流程 | 说明 |
|---|---|---|
| 半自动（默认） | 分析 → 生成方案 → 【人可编辑】→ 点应用 → FFmpeg 出片 | 留人工纠错窗口 |
| 全自动 | 分析 → 生成方案 → 【自动应用】→ FFmpeg 直接出片 | 分析完成后自动触发渲染 |

> 留"人可编辑"窗口是因为 Agent 会误判（如误删重要片段），成本极低却能兜底；产品上可做成"默认全自动，用户可关闭"。

---

## 2. 技术选型

### 2.1 已确认的选型决策

| 决策点 | 决定 | 说明 |
|---|---|---|
| 视频理解模型 | **Qwen2.5-VL，走阿里 DashScope 官方 API** | 中文视频、视频输入原生支持 |
| 用户体系 | **单用户，先跑通** | MVP 不做登录/多租户 |
| MVP op 范围 | keep/delete、speed、crop、subtitle、volume、bgm | 见 7.2 |

> 注：Qwen2.5-VL 通过 DashScope 官方 API 接入时，优先使用其 **OpenAI 兼容端点** `https://dashscope.aliyuncs.com/compatible-mode/v1`。这既满足"官方 API"，又复用 OpenAI 兼容协议，LangChain 可直接用 `ChatOpenAI`/`OpenAI` 客户端接入；后续切换 Gemini / GPT-4o / Claude 只改 `baseUrl + model + apiKey`，不改代码。

### 2.2 技术栈明细

**Java 后端（复用 AgentWrite 底座）**

| 类别 | 选型 | 理由 |
|---|---|---|
| 语言/框架 | Java 17 + Spring Boot 3.4.x | 与现有 AgentWrite 一致 |
| 模块结构 | Maven 多模块（api/app/domain/infrastructure/trigger/types） | 沿用 DDD 分层 |
| ORM | MyBatis + MySQL | 与现有一致 |
| 缓存/锁/流 | Redisson + Redis Stream | 限流、分布式锁、SSE 推流 |
| 消息队列 | RocketMQ（Outbox 模式） | 任务异步 |
| 对象存储 | MinIO（S3 协议），生产可换阿里 OSS | 视频二进制不落库 |
| 方案渲染 | FFmpeg CLI + ProcessBuilder | 确定性执行 |
| 元数据探测 | ffprobe | 读时长/分辨率/fps/音轨 |
| 方案校验 | networknt/json-schema-validator | 校验 Python 回传的方案 JSON |

> 说明：AgentCut 是**全新项目**，不引入 AgentWrite 的 Google ADK / Spring AI / armory 装配器。复用的只是「DDD 分层结构 + 任务编排范式 + 中间件配置」这些工程范式。

**Python 分析服务（新增）**

| 类别 | 选型 | 理由 |
|---|---|---|
| 运行时 | Python 3.11 | LTS，ML 库兼容好 |
| Web 框架 | FastAPI + uvicorn | ML 服务事实标准 |
| Agent | LangChain + LangGraph | 工具编排 + 多 agent 编排 |
| 结构化输出 | Pydantic v2 + `with_structured_output` | 方案 JSON 强约束 |
| 抽帧/探测 | PyAV | 精确 seek |
| 场景检测 | PySceneDetect（ContentDetector） | 现成稳定 |
| 语音转写 | FunASR | 中文最优、精确时间戳 |
| 视频理解 | Qwen2.5-VL（DashScope OpenAI 兼容端点） | 见 2.1 |

**React 前端**

| 类别 | 选型 | 理由 |
|---|---|---|
| 框架 | React 18 + TypeScript + Vite | 用户指定 |
| UI 库 | Ant Design | 表单/表格密集，中文生态 |
| 状态 | Zustand | 轻量 |
| HTTP/流 | axios + fetch 流式读 SSE | 复用后端 SSE |
| 方案编辑 | Monaco Editor(JSON) + 结构化表单 | 方案 JSON 手动编辑 |
| 时间线 | 自研轻量时间线 + WaveSurfer（二期） | 前端最大工作量 |

---

## 3. 总体架构

```
┌──────────────────────── AgentCut-front (React) ────────────────────────┐
│ 上传页 │ 分析进度(SSE) │ 分析报告展示 │ 方案编辑器(表单/JSON/时间线) │ 版本/回滚 │ 预览/导出 │
└──────────────────────────────┬─────────────────────────────────────────┘
                               │ REST + SSE
┌──────────────────────────────▼──── AgentCut-backend (Java, DDD) ───────┐
│  trigger 层: REST Controller / SSE                                      │
│  app 层:     任务编排(analyze/render 两大任务流程)                        │
│  domain 层:  project / asset / analysis / plan / task / render           │
│  infrastructure: MyBatis / OSS(MinIO) / RocketMQ / PythonClient / FFmpeg │
└──────────────────────┬──────────────────────────────┬───────────────────┘
                       │ REST 调 /analyze(传OSS URL)   │ FFmpeg 渲染
┌──────────────────────▼───────────┐   ┌───────────────▼─────────────────┐
│ AgentCut-ai (Python, LangChain)  │   │ FFmpeg + ffprobe (确定性执行)     │
│ 抽帧→场景→ASR→VLM理解→方案生成    │   │ plan JSON → filtergraph → 成片   │
└──────────────────────────────────┘   └─────────────────────────────────┘
```

### 3.1 端到端数据流

```
1. 上传视频 → Java 存 MinIO，建 Project + Asset
2. 用户点"分析" → Java 建 ANALYZE 任务 → 调 Python /analyze(videoUrl)
3. Python 分析(抽帧/场景/ASR/VLM) → 产出 analysis_report + 初版 plan JSON → 回调 Java
4. Java 存 report + plan(版本1) → 任务 SUCCESS → SSE 推给前端
5. 用户在编辑器改方案 → 保存 → 生成 plan 版本2/3/...
6. 用户点"应用" → Java 建 RENDER 任务 → plan → FFmpeg 渲染 → 出成片
7. 前端下载成片
```

---

## 4. 目录结构

### 4.1 总目录

```
E:\java\AgentCut\
├── AgentCut-backend/          # Maven 多模块
├── AgentCut-ai/               # Python 分析服务
├── AgentCut-front/            # React
├── docs/                      # 设计文档、Schema 定义(共享契约)
│   ├── AgentCut-整体设计方案.md   # 本文档
│   └── plan-schema.json          # ★ 剪辑方案 JSON Schema（唯一契约源）
└── docker-compose.yml         # 本地一键起 MySQL/Redis/RocketMQ/MinIO
```

### 4.2 AgentCut-backend（DDD，对齐 AgentWrite 风格）

```
AgentCut-backend/
├── pom.xml                              # 父 pom（spring-boot-starter-parent 3.4.x）
├── sutone-agent-cut-types/              # 通用：枚举、异常、常量、ResponseCode
├── sutone-agent-cut-api/                # 对外接口 I*Service + 请求/响应 DTO
├── sutone-agent-cut-app/                # 应用层：任务编排、装配、启动类
├── sutone-agent-cut-domain/             # 领域层（核心）
│   └── cn.sutone.cut.domain
│       ├── project/                     # 项目聚合
│       ├── asset/                       # 素材
│       ├── analysis/                    # 分析报告
│       ├── plan/                        # 剪辑方案聚合（★核心）
│       ├── task/                        # 任务（状态机）
│       ├── render/                      # 渲染
│       ├── model/entity|aggregate|valobj# DDD 模型（对齐 agent 域写法）
│       ├── adapter/port|repository      # 端口接口 + 仓储接口
│       └── service/                     # 领域服务
├── sutone-agent-cut-infrastructure/     # MyBatis 实现、OSS、RocketMQ、PythonClient、FFmpeg 封装
└── sutone-agent-cut-trigger/            # REST Controller + SSE
```

包名规则：`cn.sutone.cut.domain.plan.*`、`cn.sutone.cut.domain.task.*`（业务域 `cut`，对齐 AgentWrite 的 `cn.sutone.ai.domain.agent.*` 命名习惯）。

### 4.3 AgentCut-ai（Python）

```
AgentCut-ai/
├── pyproject.toml / requirements.txt
├── app/
│   ├── main.py                 # FastAPI 入口
│   ├── api/
│   │   └── analyze.py          # POST /analyze、GET /analyze/{id}/status
│   ├── agents/                 # LangChain agent
│   │   ├── analysis_agent.py   # 理解视频、产出分析报告
│   │   └── plan_agent.py       # 分析报告 → 剪辑方案 JSON
│   ├── tools/                  # 确定性工具（agent 可调）
│   │   ├── frame_extract.py    # 抽帧(PyAV)
│   │   ├── scene_detect.py     # 场景检测(PySceneDetect)
│   │   ├── transcribe.py       # ASR(FunASR)
│   │   └── vlm_understand.py   # VLM 理解(Qwen2.5-VL)
│   ├── schemas/                # Pydantic（与 plan-schema.json 对齐）
│   └── config.py               # 模型配置(baseUrl/apiKey/model，OpenAI 兼容)
└── tests/
```

### 4.4 AgentCut-front（React）

```
AgentCut-front/
├── src/
│   ├── pages/            # 上传、分析、编辑、预览、导出
│   ├── components/       # 方案编辑器、时间线、视频预览、进度条
│   ├── api/              # axios + SSE 客户端
│   ├── stores/           # Zustand
│   └── types/            # 与 plan-schema 对齐的 TS 类型
└── ...
```

---

## 5. 领域模型设计（DDD）

### 5.1 聚合与实体

| 聚合根 | 说明 | 内部实体/值对象 |
|---|---|---|
| **Project** | 一次剪辑项目 | Asset（源视频）、AnalysisReport、Plan |
| **Plan** | 剪辑方案（当前生效版本） | PlanVersion（历史版本）、Timeline、Segment、Operation |
| **Task** | 异步任务 | 进度、结果引用 |

### 5.2 关键值对象

```
TimeRange        { start, end }                      // 源时间区间（浮点秒）
Segment          { id, keep, sourceRange, operations[] }  // 时间线片段
Operation        { type, params }                    // 原子剪辑操作（判别联合）
OutputConfig     { width, height, fps, codec, bitrate }
SubtitleStyle    { fontSize, color, position }
Global           { output, bgm, subtitleStyle }
Transition       { from, to, type, duration }
```

### 5.3 领域服务与端口

- **PlanDomainService**：方案版本化、回滚、diff、校验。
- **RenderPlanService**：plan → 渲染中间表示（IR）。
- **端口（port）**：`IVideoAnalysisClient`（调 Python）、`IObjectStorage`（OSS）、`IRenderEngine`（FFmpeg）、`IPlanRepository`、`ITaskRepository` 等——领域层只依赖接口，实现放 infrastructure，对齐 AgentWrite 的 `adapter/port` 风格。

---

## 6. 剪辑方案 Schema（★ 核心契约）

三端并行开发的前提，`docs/plan-schema.json` 是唯一权威定义。

### 6.1 完整结构

```jsonc
{
  "schemaVersion": "1.0",          // Schema 版本，向后兼容
  "planVersion": 3,                // 方案自身版本，存档/回滚用
  "projectId": "prj_xxx",
  "source": {                      // 源视频（来自 ffprobe）
    "assetId": "asset_xxx",
    "url": "oss://.../input.mp4",
    "duration": 120.5, "fps": 30, "width": 1920, "height": 1080
  },
  "global": {                      // 全局设置
    "output": { "width": 1080, "height": 1920, "fps": 30 },
    "bgm": { "url": "oss://.../bgm.mp3", "volume": 0.3, "loop": true },
    "subtitleStyle": { "fontSize": 48, "color": "#FFFFFF", "position": "bottom" }
  },
  "timeline": [                    // 片段列表（顺序即最终顺序）
    {
      "id": "seg_001",
      "keep": true,                // false = 剪掉
      "sourceRange": { "start": 0.0, "end": 8.5 },
      "operations": [              // 段内操作，顺序执行
        { "type": "speed", "rate": 1.5 },
        { "type": "crop", "x": 0, "y": 180, "width": 1080, "height": 1920 },
        { "type": "subtitle", "text": "大家好，今天聊...", "start": 0, "end": 8.5 }
      ]
    },
    { "id": "seg_002", "keep": false, "sourceRange": { "start": 8.5, "end": 12.0 } }
  ],
  "transitions": [
    { "from": "seg_001", "to": "seg_003", "type": "fade", "duration": 0.5 }
  ]
}
```

### 6.2 操作类型注册表（可扩展原子操作）

| 类别 | op type | 关键参数 | 优先级 |
|---|---|---|---|
| 裁剪 | `keep`/`delete`（由 segment.keep 表达） | — | MVP |
| 变速 | `speed` | rate | MVP |
| 裁切 | `crop` | x,y,width,height | MVP |
| 字幕 | `subtitle` | text,start,end | MVP |
| 音频 | `volume` / `mute` | volume | MVP |
| 背景乐 | `bgm`（global 级） | url,volume,loop | MVP |
| 转场 | `transition` | type,duration | P1 |
| 滤镜 | `filter` | name,params | P1 |
| 贴纸/标题 | `textOverlay` | text,style,pos | P1 |
| 去静音 | `removeSilence`（分析期预处理） | threshold | P2 |
| 倒放/旋转 | `reverse` / `rotate` | — | P2 |

### 6.3 版本化与校验

- **校验**：Java 用 JSON Schema 校验 Python 回传的方案；Pydantic 在 Python 侧做第一道约束。
- **版本化**：每次保存产生 `plan_version` 记录，可 diff、可回滚。Agent 初稿 = 版本 1，人改后 = 版本 2、3…
- **可回放**：所有时间用绝对浮点秒 + 资源 URL 锁定，同一版本渲染结果确定性一致。

---

## 7. 视频分析 Agent 设计（Python LangChain）

### 7.1 分析流水线（确定性工具 + VLM 决策）

```
源视频
 ├─ ① 抽帧（PyAV，按场景间隔或 1fps 采样）
 ├─ ② 场景检测（PySceneDetect，切分镜头边界）
 ├─ ③ ASR（FunASR，带时间戳转写 → 字幕素材 + 内容理解）
 ├─ ④ VLM 理解（Qwen2.5-VL：逐帧/逐场景语义、对象、文字、情绪）
 └─ ⑤ 方案生成（LangChain agent：分析报告 → plan JSON）
```

### 7.2 Agent 角色拆分

| Agent | 职责 | 输入 | 输出 |
|---|---|---|---|
| AnalysisAgent | 看懂视频：段落结构、亮点、口误/静音 | 帧图 + 转写文本 | AnalysisReport |
| PlanAgent | 定策略 → 生成方案 | AnalysisReport + 用户偏好 | plan JSON |

- 用 **LangGraph** 串成顺序图；MVP 也可先单 Agent 直跑。
- **结构化输出**：PlanAgent 用 `with_structured_output` / 工具调用强制产出合法 plan，字段与 `plan-schema.json` 一致。

### 7.3 模型接入

- VLM/LLM 走 **DashScope OpenAI 兼容端点**（`baseUrl + apiKey + model`）。
- 默认 `qwen2.5-vl`；切换 Gemini/GPT-4o/Claude 只改 config，不动代码。
- ASR 默认 `FunASR`（中文、精确时间戳）；纯英文换 faster-whisper。

### 7.4 单任务处理（无长期记忆）

- 分析服务是**无状态**的：一次 `/analyze` 调用 = 一个自包含任务，输入视频 → 输出 report + plan。
- **不引入**记忆系统（无向量库、无记忆抽取/检索、无跨任务用户偏好）。
- 任务内的中间态（抽帧结果、转写文本、分析报告）仅作为本次任务的工作状态，随任务结束即释放。
- **替代方案**：用户对成片风格/时长/画幅的意图，通过 `/analyze` 的入参（`target` 约束对象）显式传入，而非从历史学习。

---

## 8. 任务编排设计（Java，复用 AiWriting 范式）

### 8.1 任务状态机

```
PENDING → RUNNING → SUCCESS
                  ↘ RETRYING（可重试异常）→ RUNNING
                  ↘ FAILED（不可恢复）
```

### 8.2 两类任务流程

| 任务 | 触发 | 编排 |
|---|---|---|
| **ANALYZE** | 用户点"分析" | 建任务 → Outbox/RocketMQ → 调 Python `/analyze` → 等回调 → 存 report+plan → SUCCESS → SSE 推送 |
| **RENDER** | 用户点"应用/预览" | 建任务 → 读 plan → 编译 FFmpeg → 分段渲染 → 拼接 → SUCCESS → 产出成片 |

### 8.3 复用点

- **Outbox + MQ**：保证"建任务 + 发消息"原子一致（对齐 AgentWrite `AiWritingService.submitTask`）。
- **心跳 + 进度**：RENDER 任务从 FFmpeg `-progress` 读进度，节流写 DB（对齐心跳 5s 节流）。
- **SSE 推送**：Redis Stream 推给前端（对齐 `taskEventPublisher`）。
- **重试**：可重试异常（限流/超时）→ RETRYING → MQ 重试；不可恢复 → FAILED。

---

## 9. 剪辑执行引擎（Java + FFmpeg）

### 9.1 编译流程

```
plan JSON → IR(中间表示) → FFmpeg filtergraph/分段命令 → 执行 → 拼接 → 成片
```

- **分段渲染**：每个 `keep` 段应用段内 ops 单独渲染 → `concat` 拼接 → 叠全局 BGM/字幕。
- **断点续传/缓存**：只重渲变更的段。
- **试剪预览**：低分辨率快速出片（480p），确认后再出高清。
- **进度**：`ffmpeg -progress pipe:1` 解析 out_time 上报。

### 9.2 代码位置

`infrastructure/render/` 下的 `FfmpegRenderEngine` 实现领域端口 `IRenderEngine`；`domain/render/` 放 plan→IR 的编译逻辑（纯函数，可单测）。

---

## 10. 数据库设计（MySQL）

| 表 | 关键字段 | 说明 |
|---|---|---|
| `project` | id, user_id, title, source_asset_id, status, created_at | 项目 |
| `asset` | id, project_id, type(SOURCE/OUTPUT/BGM/THUMBNAIL), oss_url, size, duration, width, height, fps | 素材 |
| `analysis_report` | id, project_id, version, content_json, status | 分析报告 |
| `plan` | id, project_id, current_version_id, status(DRAFT/READY/APPLIED) | 方案主表 |
| `plan_version` | id, plan_id, version_no, content_json, applied, created_by, created_at | 版本/存档 |
| `task` | id, project_id, type(ANALYZE/RENDER), status, progress, payload_json, result_json, error_msg, heartbeat_at | 任务 |
| `outbox_event` | 复用 AgentWrite 的 Outbox 模式 | 消息可靠性 |

> 单用户 MVP：`user_id` 字段先保留但固定为默认值，为后续多租户留扩展。

---

## 11. API 设计

### 11.1 Java 侧（REST + SSE）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/projects` | 创建项目 |
| POST | `/api/v1/projects/{id}/upload` | 分片上传视频 |
| POST | `/api/v1/projects/{id}/analyze` | 发起分析（返回 taskId） |
| GET | `/api/v1/tasks/{id}` | 查询任务状态/进度 |
| GET | `/api/v1/tasks/{id}/stream` | SSE 订阅进度 |
| GET | `/api/v1/projects/{id}/analysis` | 获取分析报告 |
| GET | `/api/v1/plans/{id}` | 获取方案 |
| PUT | `/api/v1/plans/{id}` | 保存方案（新版本） |
| GET | `/api/v1/plans/{id}/versions` | 版本列表 |
| POST | `/api/v1/plans/{id}/versions/{v}/rollback` | 回滚 |
| POST | `/api/v1/plans/{id}/preview` | 试剪（低清） |
| POST | `/api/v1/plans/{id}/apply` | 应用方案（出成片） |
| GET | `/api/v1/render/{taskId}/result` | 获取成片 |

### 11.2 Python 侧

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/analyze` | 提交分析（传 videoUrl + target 约束 + callbackUrl） |
| GET | `/analyze/{jobId}/status` | 查询分析进度（轮询兜底） |
| POST | `/analyze/{jobId}/callback` | 完成回调 Java（或 Java 轮询） |

`/analyze` 请求体示例（用户意图通过 `target` 显式传入，替代长期记忆）：

```jsonc
{
  "videoUrl": "oss://.../input.mp4",
  "callbackUrl": "http://backend/api/v1/analyze/callback",
  "target": {
    "aspectRatio": "9:16",      // 目标画幅
    "maxDuration": 60,          // 目标时长（秒）
    "addSubtitle": true,        // 是否加字幕
    "style": "快节奏口播"        // 风格意图（自由文本）
  }
}
```

---

## 12. 前端设计

| 页面 | 核心组件 |
|---|---|
| 上传页 | 分片上传、进度 |
| 分析页 | SSE 进度条、分析报告展示（场景/转写/亮点） |
| 编辑页 | 方案编辑器：结构化表单 + JSON 编辑器（Monaco）+（二期）可视化时间线 |
| 预览/导出页 | 试剪预览、版本对比、下载成片 |

> MVP 建议：编辑页先用「表单 + Monaco JSON」顶住，可视化时间线放二期。

---

## 13. 关键技术难点与应对

| 难点 | 应对 |
|---|---|
| Agent 生成方案质量不稳定 | Schema 强约束 + 结构化输出 + 试剪快速纠错 |
| 长视频分析成本/耗时 | 抽帧采样 + 分段并行 + 缓存分析结果 |
| FFmpeg 编译正确性 | plan→IR 纯函数化，可单测；分段渲染降低复杂度 |
| 大文件上传/存储 | 分片 + 秒传 + OSS，转码预览用 HLS |
| 可回放性 | 绝对时间 + 资源 URL 锁定 + 版本化 |

---

## 14. 里程碑计划

| 里程碑 | 范围 | 交付 |
|---|---|---|
| **M1（打通闭环）** | 上传 → 抽帧+ASR → 生成"删除静音/保留亮点"简单方案 → 表单/JSON 编辑 → FFmpeg 出片 | 端到端可用 |
| **M2** | 可视化时间线、方案版本/回滚、试剪预览 | 编辑体验完善 |
| **M3** | 多 Agent 分析、更多 op（变速/裁切/转场）、GPU 加速 | 能力增强 |
| **M4** | 模板、批量、用户偏好学习 | 规模化 |

---

## 15. 决策记录（ADR）

| # | 决策 | 结论 | 日期 |
|---|---|---|---|
| 1 | 项目形态 | 全新项目 AgentCut，三子包 backend/ai/front | 2026-08-27 |
| 2 | Agent 引擎 | 仅 Python LangChain，Java 侧无 LLM | 2026-08-27 |
| 3 | 视频理解模型 | Qwen2.5-VL，走 DashScope OpenAI 兼容端点 | 2026-08-27 |
| 4 | 用户体系 | 单用户先跑通，不做登录/多租户 | 2026-08-27 |
| 5 | MVP op 范围 | keep/delete、speed、crop、subtitle、volume、bgm | 2026-08-27 |
| 6 | 方案渲染 | Java + FFmpeg，plan→IR→filtergraph | 2026-08-27 |
| 7 | 记忆系统 | 不做长期记忆，仅单任务无状态处理；用户意图走 `/analyze` 的 `target` 入参 | 2026-08-27 |
| 8 | 应用模式 | 先实现半自动（人可编辑）跑通 M1，全自动后续再加 | 2026-08-27 |
