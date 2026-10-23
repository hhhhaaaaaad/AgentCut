# 现有 PlanAgent 的受控迭代

日期：2026-10-23。运行路径仍为 `AnalysisReport → Plan 1.0`，策略标识为 `LEGACY_PLAN`。

## 执行顺序

1. 导演生成完整 Plan JSON，程序进行结构解析与非有限数字检查。
2. 评审前恢复受保护场景，再执行确定性 Validator。源素材标识、URL、时长和尺寸等必须与报告一致；所有源区间（包括删除片段）必须合法，至少保留一个片段。
3. 只有硬校验通过的候选才交给 QA。QA 收到完整报告中的原始转写、场景、亮点、章节和依赖证据。
4. 结构失败、硬错误或 QA 问题作为反馈，最多生成三轮。只有 `passed=true`、分数达到用户阈值且没有 `high` 问题，才停止修订。
5. 后续生成失败或预算耗尽时，保留之前的硬合格草稿。候选排序依次比较：QA 达标、没有已知 high 问题、有可用评审、评分；同分保留较早版本。没有可用 QA 的候选也属于草稿。
6. 没有硬合格候选时使用规则兜底，并再次校验。兜底仍非法则任务失败；不向下游交付非法方案。
7. 最终交付前仅重新校验，不再修改已评审候选。重复调用同一个 Agent 会清空上一次的评审与执行记录。

QA 调用异常/超时或解析失败时，不继续调用 QA，也不捏造评审；保留硬合格草稿并要求人工复核。

## 执行记录与候选绑定

分析结果新增可选 `result.analysis.planning`，随已有报告 JSON 保存，无数据库迁移。
旧报告没有此字段时保留原兼容行为。Plan 1.0 字段和 B1 契约没有变化。

| 字段 | 含义 |
|---|---|
| `version` / `strategy` | `1.0` / `LEGACY_PLAN` |
| `hashScope` | `PYTHON_PLAN_1_0` |
| `attempts` | 每轮 outcome、候选 hash、硬校验结果、原始 QA 结果和耗时 |
| `selectedCandidateHash` / `selectedIteration` | 实际返回候选及来源轮次；规则兜底没有轮次 |
| `planSource` | `REAL` 或 `DETERMINISTIC_FALLBACK` |
| `validation` | 最终方案的硬校验结果与警告 |
| `reviewStatus` / `reviewReasons` | `READY` / `NEEDS_REVIEW` 与确定性原因码 |
| `stopReason` | 达标、轮次耗尽、预算耗尽、QA 不可用、无合法候选或确定性模式 |

哈希使用 Python 返回的 `Plan.to_contract_dict()`，按键排序、紧凑 UTF-8 JSON、
拒绝 NaN/Infinity 后计算 SHA-256。它是旧浮点秒 Plan 的局部候选标识，不是 B1 跨语言 canonical hash。
每轮 QA 的 `candidateHash` 由程序覆盖；顶层 `quality` 始终对应选中的同一候选。
顶层 `quality.passed` 会按阈值和 high 问题收紧；`attempts[].quality` 保留模型原始通过标记。

绑定范围为 Python 返回的原始 Plan，以及 Java 任务 `resultJson` 保存的该份 JSON。
Java 现有方案仓储仍会回填 projectId、必要时回填 URL，并重新序列化；哈希不代表经过这些改写后的当前方案或人工修改版本。

## 完成与质量分离

Python 的 `success` 表示本次计算完成并有硬合格方案。以下任一情况要求人工复核：

- 规则兜底，或 QA 不可用。
- QA 未通过、低于阈值或仍有 high 问题。
- Validator 有警告。
- 分析为模拟、局部降级，或缺少 ASR/VLM 来源信息。明确的 ASR `NO_SPEECH` 可用，不视为降级。

Java 读取 `analysis.planning.reviewStatus`，把上述草稿保存为 `NEEDS_REVIEW`。
新版声明 `READY` 时还要求 QA 通过，且 QA hash 与选中候选 hash 一致；缺失、非法或不匹配都进入人工复核。
旧 `quality.passed=false` 仍可独立触发复核，迟到回调不能覆盖终态。

## 预算与能力边界

`AGENTCUT_AI_QA_BUDGET` 在发起每轮导演调用和 QA 调用前检查，耗尽后不启动下一次调用。
它不是正在执行的同步 SDK 调用的强制中止期限；单次请求仍受已有模型客户端 timeout/max_retries 控制。
本轮未引入新 Agent 框架、调用取消、线上任务恢复或新的重试层。

这是现有决策闭环的可靠性改进，不代表多模态融合、MaterialIndex、ID 导演和 EditingScript 编译已完成。
完整报告加入 QA 可以提供现有证据，但无法补足旧报告本身没有分析过的源区间。
模拟 HTTP/LLM 验证不代表真实模型的剪辑效果验收。

## 离线验收

```bash
cd AgentCut-ai
AGENTCUT_LOAD_DOTENV=false AGENTCUT_AI_SIMULATE=true AGENTCUT_LLM_API_KEY='' AGENTCUT_VLM_API_KEY='' python -m pytest -q
```

新增测试通过注入本地 stub 验证：先校验再 QA、坏 JSON 修订、后续失败保留最佳草稿、
评分/通过标记/high 的共同约束、预算耗尽、QA 不可用、候选 hash、重复运行隔离、
来源/区间伪造拒绝、模拟与来源缺失标记，以及异步 API 交付记录。
Java 内存仓储联调验证草稿保存、候选评审不匹配、旧结果兼容与终态守卫。

本批本地验证：Python 3.14 全量 416 项通过（新增 35 项），Java 17 全量 142 项通过
（新增 10 项），Maven `verify` 打包成功。未调用真实模型。
