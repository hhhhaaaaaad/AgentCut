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

## 快速开始

### 1. 基础设施（本地中间件）

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

## 文档

- `docs/AgentCut-整体设计方案.md`：权威设计文档
- `docs/plan-schema.json`：剪辑方案 JSON Schema（唯一契约源，三端共用，本骨架未改动）
