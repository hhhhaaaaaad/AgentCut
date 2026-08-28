# AgentCut — 视频智能剪辑平台

> 单仓库三子包：`AgentCut-backend`(Java) + `AgentCut-ai`(Python) + `AgentCut-front`(React)

## 项目概述

视频智能剪辑：**上传 → Agent 分析 → 生成/编辑剪辑方案 → 应用方案 → 输出成片**。

核心设计原则：**剪辑方案文档是单一事实来源** —— Agent 生成它、人可编辑它、引擎执行它、系统存档它，四者共用同一份文档（Schema 唯一契约见 `docs/plan-schema.json`）。

设计细节见权威文档 `docs/AgentCut-整体设计方案.md`。

## 三个子包

| 子包 | 技术栈 | 职责 |
|---|---|---|
| `AgentCut-backend` | Java 17 + Spring Boot 3.4.x，Maven 多模块（DDD 分层） | REST/SSE 接口、任务编排、FFmpeg 渲染、持久化 |
| `AgentCut-ai` | Python 3.11 + FastAPI + LangChain | 抽帧/场景检测/ASR/VLM 理解 → 生成剪辑方案 |
| `AgentCut-front` | React 18 + TypeScript + Vite + Ant Design | 上传、分析进度、方案编辑器、预览导出 |

## AgentCut-backend 模块结构

Maven 多模块（DDD 分层），`groupId=cn.sutone`，包名 `cn.sutone.cut.*`：

| 模块 | 职责 |
|---|---|
| `sutone-agent-cut-types` | 通用：枚举、异常、常量 |
| `sutone-agent-cut-api` | 对外接口 + 请求/响应 DTO |
| `sutone-agent-cut-domain` | 领域层（project/asset/analysis/plan/task/render） |
| `sutone-agent-cut-app` | 应用层：任务编排 + 启动类 |
| `sutone-agent-cut-infrastructure` | MyBatis / OSS / RocketMQ / PythonClient / FFmpeg 实现 |
| `sutone-agent-cut-trigger` | REST Controller + SSE |

模块依赖关系：`app → domain + infrastructure`；`domain → types`；`infrastructure → domain`；`trigger → app + api`；`api → types`。

## 前置依赖

- **ffmpeg + ffprobe（必装）**：渲染引擎通过 ProcessBuilder 调用，需在 PATH 中。Windows 从 [ffmpeg.org](https://ffmpeg.org) 下载 static build 并加入 PATH；macOS `brew install ffmpeg`；Linux `apt install ffmpeg`。缺了它「应用方案」步骤会报错。
- **Docker（可选）**：`docker-compose.yml` 提供 MySQL/Redis/RocketMQ/MinIO。但 MVP 骨架用**内存仓储 + 本地文件存储**，不起数据库也能跑通「分析→编辑→渲染」主流程。
- Java 17、Python 3.11+、Node 18+。

## 快速开始

### 1. 基础设施（本地中间件，可选）

```bash
docker compose up -d
```

启动 MySQL(3306) / Redis(6379) / RocketMQ(9876,10911) / MinIO(9000,9001)，默认账号密码见 `docker-compose.yml`。

### 2. 后端（Java）

```bash
cd AgentCut-backend
mvn -pl sutone-agent-cut-app -am spring-boot:run
# 健康检查：GET http://localhost:8080/api/v1/health
```

### 3. AI 分析服务（Python）

```bash
cd AgentCut-ai
pip install -r requirements.txt
# 未设置 DASHSCOPE_API_KEY 时走模拟模式（SIMULATE=true，工具返回占位数据，服务可端到端跑通）
export DASHSCOPE_API_KEY=<你的密钥>
uvicorn app.main:app --reload --port 8000
# 健康检查：GET http://localhost:8000/health
```

### 4. 前端（React）

```bash
cd AgentCut-front
npm install
npm run dev
# 打开 http://localhost:5173
```

## API 清单（Java 后端）

统一前缀 `/api/v1`，base-url 一律用 `http://127.0.0.1:8080`（勿用 `localhost`，Windows IPv6 解析会踩坑）。

### 项目（Project）

| 方法 | 路径 | 说明 | 请求体 |
|---|---|---|---|
| POST | `/projects` | 创建项目 | `{ "userId": 0, "title": "..." }` |
| GET | `/projects?userId=0` | 项目列表 | — |
| GET | `/projects/{projectId}` | 查询项目 | — |
| PUT | `/projects/{projectId}` | 更新标题/状态 | `{ "title": "...", "status": "..." }` |
| DELETE | `/projects/{projectId}` | 删除项目 | — |

### 素材（Asset）

| 方法 | 路径 | 说明 | 请求体 |
|---|---|---|---|
| POST | `/projects/{projectId}/upload` | 上传源视频（建 SOURCE 素材） | multipart，字段名 `file` |
| GET | `/projects/{projectId}/assets` | 项目素材列表 | — |
| GET | `/assets/{assetId}` | 查询素材 | — |
| DELETE | `/assets/{assetId}` | 删除素材 | — |

### 分析报告（AnalysisReport）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/projects/{projectId}/analysis` | 项目最新一份分析报告 |
| GET | `/analysis/{reportId}` | 按 ID 查询报告 |

### 任务（Task）

| 方法 | 路径 | 说明 | 请求体 |
|---|---|---|---|
| POST | `/projects/{projectId}/analyze` | 发起分析（返回 taskId） | `{ "aspectRatio", "maxDuration", "addSubtitle", "style" }` |
| GET | `/tasks/{taskId}` | 查询任务状态/进度 | — |
| GET | `/projects/{projectId}/tasks` | 项目任务列表 | — |
| POST | `/analyze/callback?taskId=...` | Python 分析完成回调（内部） | `{ "result": { "analysis": {...}, "plan": {...} } }` |

### 方案（Plan）

| 方法 | 路径 | 说明 | 请求体 |
|---|---|---|---|
| GET | `/plans/{projectId}` | 获取当前方案 | — |
| PUT | `/plans/{projectId}` | 保存方案（生成新版本） | 方案 JSON（对齐 `docs/plan-schema.json`） |
| GET | `/plans/{projectId}/versions` | 版本号列表 | — |
| POST | `/plans/{projectId}/versions/{versionNo}/rollback` | 回滚到指定版本 | — |
| POST | `/plans/{projectId}/apply` | 应用方案（FFmpeg 渲染出片） | — |

### 成片（Render）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/render/{taskId}/result` | 查询渲染结果（成片 outputPath） |
| GET | `/render/{taskId}/download` | 下载成片文件（流式返回，`Content-Disposition: attachment`） |

### 健康检查

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 后端健康检查 |

## 端到端联调步骤

> 全程用 Git Bash（勿用 PowerShell），base-url 一律 `127.0.0.1`，测试 JSON 用英文/数字避免 GBK 乱码导致 400。

### 1. 启动三端

```bash
# 后端（8080）
cd AgentCut-backend && mvn -pl sutone-agent-cut-trigger spring-boot:run
# AI 分析（8000，模拟模式无需 DashScope key）
cd AgentCut-ai && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# 前端（5173）
cd AgentCut-front && npm install && npm run dev
```

健康检查：`curl -s http://127.0.0.1:8080/api/v1/health` 返回 `{"status":"ok"}`。

### 2. 建项目

```bash
curl -s -X POST http://127.0.0.1:8080/api/v1/projects \
  -H "Content-Type: application/json" -d '{"userId":0,"title":"my-video"}'
# → 记下返回的 projectId（如 1）
```

### 3. 上传源视频

```bash
curl -s -X POST http://127.0.0.1:8080/api/v1/projects/1/upload \
  -F "file=@/e/java/AgentCut/test_video.mp4"
# → 返回 SOURCE 素材，ossUrl 形如 file://...
```

### 4. 保存方案（source.url 指向上传的本地文件路径）

```bash
curl -s -X PUT http://127.0.0.1:8080/api/v1/plans/1 \
  -H "Content-Type: application/json" \
  -d '{"schemaVersion":"1.0","planVersion":1,"projectId":"1","source":{"assetId":"1","url":"<上一步的本地文件路径>","duration":60,"fps":30,"width":1920,"height":1080},"global":{"output":{"width":640,"height":360,"fps":30}},"timeline":[{"id":"seg_1","keep":true,"sourceRange":{"start":0,"end":10}}]}'
```

### 5. 发起分析（模拟模式，Python 返回占位报告+方案）

```bash
curl -s -X POST http://127.0.0.1:8080/api/v1/projects/1/analyze \
  -H "Content-Type: application/json" \
  -d '{"aspectRatio":"9:16","maxDuration":60,"addSubtitle":true,"style":"fast"}'
# → 返回 taskId，轮询 GET /tasks/{taskId} 到 SUCCESS
```

### 6. 应用方案（FFmpeg 渲染出片）

```bash
curl -s -X POST http://127.0.0.1:8080/api/v1/plans/1/apply
# → 返回 {"outputPath":"./data/work/output.mp4",...}
```

### 7. 查询渲染任务并下载成片

```bash
# 找到 RENDER 任务 taskId
curl -s http://127.0.0.1:8080/api/v1/projects/1/tasks
# 下载成片
curl -s -o output.mp4 http://127.0.0.1:8080/api/v1/render/{taskId}/download
```

> 一键冒烟：`bash verify.sh`（覆盖建项目 / 存方案 / 查询 / 模拟分析）。

## MyBatis 持久化（MySQL，可选）

MVP 默认走**内存仓储**（`InMemory*Repository`），不起数据库也能跑通全流程。已提供完整的 MyBatis 持久化实现，按 profile 切换：

| Profile | 仓储实现 | 依赖 |
|---|---|---|
| `local`（默认） | 内存仓储 + 本地文件存储 | 无 |
| `mysql` | MyBatis Mapper + MySQL | 需启动 `agentcut-mysql`（宿主机 `13307`） |

### 切换到 MySQL

```bash
# 1. 启动 MySQL（docker 可用时）
docker compose up -d mysql
# 2. 建表（7 张表）
mysql -h127.0.0.1 -P13307 -uroot -proot123456 < docs/schema.sql
# 3. 以 mysql profile 启动后端
cd AgentCut-backend && SPRING_PROFILES_ACTIVE=mysql mvn -pl sutone-agent-cut-trigger spring-boot:run
```

### 实现要点

- 数据源：`infrastructure/config/MybatisConfig`（`@Profile("mysql")`）手动建 `HikariDataSource`，`@MapperScan` 注册 `cn.sutone.cut.infrastructure.persistence.mapper` 下的 5 个 Mapper。
- 仓储：`Mybatis*Repository`（`@Profile("mysql")`）实现 domain 的 5 个 `I*Repository` 接口；内存实现加 `@Profile("!mysql")`，二者互斥。
- 方案内容存 `plan_version.content_json`（JSON 文档），`plan.current_version_id` 指向当前版本，查询时 join 取回 JSON 用 `PlanJsonMapper` 反序列化。
- 连接信息：`application-mysql.yml`（`127.0.0.1:13307`，`root/root123456`，库 `agentcut`）。

> 注：docker 引擎不可用（`\\.\pipe\dockerDesktopEngine` 报错）时，MyBatis 代码已完成、可编译、装配正确（mysql profile 可正常启动并正确建立连接池），但实际 SQL 执行需 MySQL 运行。内存模式不受影响。

## 文档

- `docs/AgentCut-整体设计方案.md`：权威设计文档
- `docs/plan-schema.json`：剪辑方案 JSON Schema（唯一契约源，三端共用，本骨架未改动）
- `docs/schema.sql`：MySQL 建表脚本（7 张表，切换 MyBatis 持久化时使用）
