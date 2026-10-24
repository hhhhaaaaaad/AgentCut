# 新脚本语义 QA 与有限 ID 修订

日期：2026-10-24。状态：实现独立离线闭环；在线任务仍使用原协议。
依赖素材索引与 ID 导演（PR #4），不依赖音轨适配或旧 PlanAgent 质量闭环。

## 执行流程

```text
硬合格 ID 草稿
  → 完整证据语义 QA
  → 添加语义风险 / 生成质量汇总
  → 未达标时修改 ID 选择
  → 程序重新编译与硬校验
  → 新候选重新 QA
  → 选择历史最佳硬合格候选，或保留未评审草稿
```

实现：`app/agents/script_review_agent.py`、`app/analysis/script_review.py`、
`app/analysis/offline_script_review.py`。模型适配器仅通过 `invoke(prompt)` 显式注入，
要求独立声明 REAL/SIMULATED 来源；不构造 SDK 客户端，不读取 `.env`。

## QA 输入与输出

QA 输入包含当前完整脚本、当前 candidateHash、用户目标、完整 MaterialIndex、
选中单元前后邻接关系。索引同时包含未选中单元、原始转写、视觉观察和依赖声明，
可以回查被遗漏的内容，不只根据剪辑方案自评。
这里的视觉证据是已有观察记录，未新增像素级图像审核。

`ScriptAssessment` 严格要求 candidateHash、passed、overallScore、issues、summary。
每条问题注明类型、LOW/MEDIUM/HIGH、当前行 rowRefs、索引单元 unitRefs、原因和修改建议；
还可引用原始 transcriptId/frameId/sceneId。未知引用、重复引用、过期 hash、
额外字段、重复 JSON 键及非有限数字会使本轮 QA 不可用，不产生质量通过标记。
引用合法只能证明证据存在，不能证明模型的语义判断必然正确。

程序同时检查 passed、质量阈值（默认 0.85）和 HIGH 问题。
未达阈值或仍有问题时可修订；即使评分通过，残留风险也要求 NEEDS_REVIEW。
修订仍只接受合法 ID/角色/理由/人工建议，原话和双时间由程序重新派生。

## 候选 hash 与评审元数据

风险清单参与 B1 scriptHash，而语义问题来自评审。为避免把原始评审偷偷改绑到另一版：

1. 模型的原始 assessment.candidateHash 始终绑定它实际收到的完整输入草稿。
2. 程序只把评审投影为风险、行 riskRefs、校验和质量元数据；不修改原话、源区间、
   输出时间、标题、目标、行角色、理由、包装建议或 manualNotes。
3. 保存 `ReviewPublication`：reviewedCandidateHash、publishedCandidateHash、unchangedContentHash。
4. unchangedContentHash 只排除上述派生评审字段，其余内容必须完全一致。
5. B1 QualityReport 是程序生成的质量汇总，绑定发布版本的 scriptHash；它不是被改写 hash 的原始模型响应。
6. 修订选材会生成另一份完整候选，必须重新硬校验、重新 QA，不复用上版 assessment。

保存的 `ScriptReviewArtifact` 保留初始输入、全部评审候选、原始 assessment、发布映射、
修订尝试及最终选择。读入时从原始索引/决策重新编译候选，重新派生风险与质量，并验证最佳版本选择。
手动重封 hash 不能使伪造原话、不同版本评审或被清除的基础风险通过回放校验。
这些校验不构成对真实模型调用的密码学证明；适配器来源仍需由受信执行端如实提供。

## 风险和 READY 条件

只有本编译器生成的“QA 不可用 / 待语义评审”占位风险可由有效 QA 元数据替换。
COARSE_ALIGNMENT、UNTRUSTED_SOURCE、VISUAL_UNVERIFIED、MISSING_DEPENDENCY、
SUBTITLE_UNAVAILABLE 等基础风险不能被模型清除。
模型发现的语义问题转换为 REVIEW 风险，不能自行签发确定性 HARD 结论。

READY 要求：硬校验通过、真实 QA 按策略通过、没有任何残留风险、来源满足 B1 要求。
模拟 QA 的原始 passed 可以为 true，但程序 QualityReport.passed 为 false，并显式保留模拟风险。
模拟导演修订也不能借真实 QA 隐去来源。粗块和缺帧即使语义评分达标仍保持 NEEDS_REVIEW。
程序未推断未知依赖；模型或人工仍可能漏判原意。

## 调用预算与失败保留

- 默认最多 3 轮 QA、2 次单次 ID 修订调用，共最多 5 次业务调用。
- 硬非法修订不消耗 QA 调用，可使用剩余修订次数修正；不套用 IDDirectorAgent 的三轮调用，避免业务重试相乘。
- QA 与修订共享默认 180 秒启动预算。超时/预算后的晚到结果被丢弃，不声称远端调用已取消。
- SDK 超时与重试必须由注入适配器配置；这里不强制中断正在执行的同步请求。
- 默认完整上下文最多 128 个单元、160,000 提示词字符，响应最多 40,000 字符。
  超限不截断证据；保留硬合格草稿并记录 CAPACITY_EXCEEDED。
- QA 不可用时不捏造评分。后续修订失败或 QA 超时时，保留按策略排名最好的硬合格候选及其对应评审。
- 排名依次比较：按阈值通过且无问题、按阈值通过、没有已知 HIGH 问题、有合法评审、评分；同分选较早版本。
  这是有限候选比较，不宣称语义最优或约束数学不可行。
- 日志产物只记录固定错误类别，不保存 SDK/解析器可能回显的原始异常文本。

## 离线复现

在 `AgentCut-ai` 下运行：

```bash
python -m app.analysis.offline_id_director \
  --input ../docs/contracts/offline-id-director.input.json \
  --output /private/tmp/agentcut-id-director.json

python -m app.analysis.offline_script_review \
  --input /private/tmp/agentcut-id-director.json \
  --replies ../docs/contracts/offline-script-review.replies.json \
  --output /private/tmp/agentcut-script-review.json \
  --bundle-output /private/tmp/agentcut-script-review.bundle.json
```

样例完全虚构：第一轮指出原文已有的关机提醒未选入，导演按合法 ID 补回，再评审。
2 轮 QA、1 次修订，选中第 2 轮的 3 行、7 秒脚本。由于来源模拟且有粗对齐等风险，结果为 NEEDS_REVIEW。
CLI 只允许 SIMULATED 录制回复，不会连接模型；把回复文件标成 REAL 会被拒绝。
省略 `--replies` 则保留未评审草稿。

`scripts/generate_script_review_fixture.py` 重现回复、摘要与实际发布的 B1 bundle。
Python、Java、TypeScript 都读取程序生成的样例；测试中的 REAL 声明仅用于虚构数据的策略断言，
不是付费模型调用或真实剪辑效果验收。

本分支验收：Python 3.14 全量 484 项通过（本轮新增 52 项），Java 17 全量 134 项通过并完成
`mvn verify`；前端 85 组共享 B1 样例及两个程序生成样例通过。

## 范围

本轮完成新脚本的语义 QA/修订离线切片。未切换在线分析/保存协议，未读取模型凭证、
未进行真实模型效果验收、未处理音轨或自动渲染。
下一步接在线输入快照、任务结果保存与策略入口，继续保持旧 Plan 1.0 可读。
