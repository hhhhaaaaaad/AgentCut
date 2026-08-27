## Handoff: team-plan → team-exec

- **Decided**: 三 worker 分工——worker-1 做三子包骨架(backend/ai/front + docker-compose + README)；worker-2 做 A(Python 分析服务)；worker-3 做 B(Java 后端+FFmpeg)。A/B 依赖骨架，先骨架后并行。
- **Rejected**: 让 A/B worker 与骨架 worker 同时并行启动（A/B 需要骨架目录/pom/依赖，会冲突）；无。
- **Risks**: 骨架的 pom 模块依赖必须正确(app→domain→types, infra→domain, trigger→app+api)；worker 间文件冲突靠"骨架只建空壳、A/B 只填业务"划界规避。
- **Files**: docs/AgentCut-整体设计方案.md（权威设计）、docs/plan-schema.json（唯一契约）。
- **Remaining**: A、B 的具体实现；前端 C 阶段(不在本批次)；端到端联调。
