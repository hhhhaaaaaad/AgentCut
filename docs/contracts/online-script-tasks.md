# B3a：准备索引的在线脚本任务

2026-10-24。新增独立任务入口，执行已有 B2 的索引构建、ID 导演、脚本编译与 QA 门禁。
本批使用运维人员准备的 `OfflineDirectorInput`，默认规则选材、语义 QA 不可用，产出明确的
`NEEDS_REVIEW` 草稿。不会自动构造收费模型、读取 `.env`、下载媒体或执行视频渲染。

这是 B3 的首个在线切片。新视频上传、真实文件 hash/probe 准入、HTTP 视频预览、MySQL
事务与进程重启恢复尚未接入。目录内声明的素材 hash/来源不能替代实际文件核验；
虚构样例仅证明协议和保存机制，不证明真实剪辑效果。

## 入口与保存边界

Java 仅在 `local` 且不含 `mysql` profile，并显式设置
`agentcut.script-tasks.enabled=true` 时注册新入口。默认关闭，MySQL 模式不回退到内存任务。
旧 `/analyze`、Plan、报告、渲染接口继续使用原协议。

| Java API | 用途 |
|---|---|
| POST `/api/v1/projects/{projectId}/script-tasks` | 接收 B1 `AnalyzeInputV1`，返回 202 和任务详情 |
| GET 同一路径 `?offset=0&limit=20` | 项目任务分页，最新创建在前，limit 为 1～100 |
| GET `/api/v1/script-tasks/{taskId}` | 身份、输入、阶段、进度、受理状态与结果可用性 |
| GET `/api/v1/script-tasks/{taskId}/script` | 当前任务不可变 `EditingScriptV1` |
| GET `/api/v1/script-tasks/{taskId}/result` | 经上下文校验的完整 B1 bundle |
| GET `/api/v1/script-tasks/{taskId}/evidence` | 保存的 sourceIndex、evidence、indexVersion |
| POST `/api/v1/script-tasks/{taskId}/reconcile` | 查询原 runId，补收丢失回调；不重新执行 |
| POST `/api/v1/script-tasks/{taskId}/events` | Python 专用事件入口，要求每任务私有 token header |

输入显式选择 `assetId`，从配置的 `<prepared-dir>/<projectId>/<assetId>.json` 加载。
目录由本地操作者维护，没有 HTTP 文件导入接口；客户端不能指定路径、callbackUrl、模型或
执行命令。检查项目存在、目录归属、素材 ID、路径与符号链接边界，随后保存文件内容快照。
此处的素材 ID 来自准备索引目录，尚未作为旧 Asset 表的 READY 上传资产接入。

Java 同一聚合锁内发布索引、决策、脚本、事件历史与终态。验证失败时不发布脚本，也不推进
进度。保存前还把 `analysisRef` 的 ID、revision、hash 绑定到该任务已保存的原始 evidence。
查询返回独立副本；结果中的 callbackUrl 去除私有 token，该字段不参与 inputHash。
每个任务保存自己的产物，不写项目“当前方案”指针，不把新脚本写入旧 Plan 表。
脚本 revision 是这次生成内的候选修订号，不冒充项目历史版本号。

保存目前为**进程内存**：Java 和 Python 默认各保留最多 64 个任务，Python 最多 2 个正在
计算的任务，没有排队或自动淘汰。容量耗尽返回 503；重启会丢失任务和去重记录。
刷新页面、重新查询可恢复服务仍存活的结果，不能据此宣称持久化或重启续跑。

## 幂等、回调与受理未知

- Java 按项目内 requestId 预留任务。同键相同输入返回原任务，不重复读取目录或调用 Python；
  同键不同输入返回 409。输入快照、runId、attempt、inputHash 在首次创建后不变。
- Python `POST /v1/script-runs` 接收 `{prepared: OfflineDirectorInput}`。同 runId、同完整
  快照返回相同 202 受理凭据；同 runId 的输入、证据或回调地址变化返回 409。
- 受理响应必须为 202，且协议、runId/jobId、taskId、inputHash 和 accepted 状态全部匹配。
  超时、5xx、重定向、非法 202 归为受理未知；明确 4xx/503 拒绝保留失败任务。
  客户端设置完整响应期限、响应体容量限制，无 POST 自动重试。
- `/reconcile` 只 GET 原 runId。远端已受理但尚未开始、正在运行或已完成均可协调；
  404 或网络不可达不能证明没有执行，保持不确定状态，不生成替代 runId。
- 回调要求身份完全一致、sequence 前进、progress 单调。重复事件幂等，同 eventId 改内容
  返回 409；旧身份、乱序和终态后的新事件忽略。失败事件不能携带合格脚本。
- Python 回调只允许 `AGENTCUT_SCRIPT_CALLBACK_BASE` 对应的精确源和任务路径，不跟随重定向。
  URL 中的每任务 token 通过 `X-AgentCut-Run-Token` header 发送；查询、补发 Python 结果也要求
  同一 header。Java 对外详情和结果不泄露 token。这不是完整的生产用户鉴权系统。
- 回调失败不会删除 Python 的终态结果。Java 可主动协调，或操作者携带 token 调用
  `POST /v1/script-runs/{runId}/callback` 补发同一结果。

Python 独立入口 `app.api.script_runs:create_script_app --factory` 不加载旧配置或模型 SDK。
旧 `app.main` 只有在 `AGENTCUT_SCRIPT_RUNS_ENABLED=true` 时额外挂载新路由。
默认执行规则导演，再经过新 QA 门禁；QA 未配置时保存 `QA_UNAVAILABLE` 风险，不制造评分。
`NO_CANDIDATE` 返回明确失败、进度小于 100、正常产物为空。

资源边界：Java 用户输入最大 64 KB；准备输入 5 MB；结果/回调 20 MB；每任务最多 1024 条
已接受事件。当前执行器用于有限准备索引，不能据此宣称长视频调度、模型硬取消或持久恢复。

## 本地复现

需要 Python 3.11+、运行依赖与 Java 17。以下均使用虚构离线 fixture，不需要密钥。
在仓库根目录执行，先创建独立的准备目录（已有条目不会覆盖）：

```sh
AgentCut-ai/.venv314/bin/python scripts/export_prepared_script_input.py \
  --input docs/contracts/offline-id-director.input.json \
  --catalog-dir /private/tmp/agentcut-script-catalog-b3a --project-id 1
```

Python 终端，从 `AgentCut-ai` 目录启动独立应用：

```sh
AGENTCUT_SCRIPT_CALLBACK_BASE=http://127.0.0.1:8081 \
  .venv314/bin/python -m uvicorn app.api.script_runs:create_script_app \
  --factory --host 127.0.0.1 --port 8001
```

Java 完成 `mvn verify` 后，从 `AgentCut-backend` 目录启动：

```sh
java -jar sutone-agent-cut-trigger/target/sutone-agent-cut-trigger-1.0.0-SNAPSHOT.jar \
  --server.address=127.0.0.1 --server.port=8081 \
  --agentcut.script-tasks.enabled=true \
  --agentcut.script-tasks.prepared-dir=/private/tmp/agentcut-script-catalog-b3a \
  --agentcut.python.base-url=http://127.0.0.1:8001 \
  --agentcut.callback.base-url=http://127.0.0.1:8081
```

新进程第一次创建的项目通常为 1；如果返回其他 ID，用实际 ID 重新导出目录：

```sh
curl -X POST http://127.0.0.1:8081/api/v1/projects \
  -H 'Content-Type: application/json' --data '{"title":"B3a fictional smoke"}'
AgentCut-ai/.venv314/bin/python scripts/smoke_script_tasks.py \
  --base-url http://127.0.0.1:8081 --project-id 1 \
  --input docs/contracts/offline-id-director.input.json
```

2026-10-24 实际双服务 HTTP 验收：2 行、6000 ms 的 NEEDS_REVIEW 草稿成功保存并通过 Python
B1 上下文回读；重复请求返回原 taskId、同键变更 409、无匹配主题 FAILED 且没有脚本。
测试未读取媒体、未调用真实 ASR/VLM/LLM，未验证 MySQL 或真实上传文件。
本地回归：Python 629 项、Java 170 项通过，前端共享契约检查通过。

下一批 B3b：流式上传、可信对象键/hash/probe 与 READY 准入，并把服务器生成的证据接入该
任务入口；随后完成 MySQL 事务/唯一约束和预览接口，再推进 B4 七列工作台。
