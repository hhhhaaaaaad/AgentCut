# B1 脚本与任务契约 1.0

状态：已实现独立类型、结构与上下文校验、共享离线样例。运行中的 AnalysisReport、
Plan 1.0 和任务端点仍使用旧协议。真实索引、分窗融合、脚本生成及服务端幂等提交
分别属于 B2/B3。样例为虚构数据，不能作为真实模型效果证明。

## 权威定义与生成

权威模型：AgentCut-ai/app/schemas/script_contracts_v1.py。

| 契约 | 用途 | 版本字段 |
|---|---|---|
| MaterialIndexV1 | 完整镜头索引、原始转写、观察与可选择单元 | indexSchemaVersion |
| DirectorDecisionV1 | 合法单元 ID、内容作用、理由与包装建议 | decisionSchemaVersion |
| EditingScriptV1 | 七列脚本的唯一保存快照 | scriptSchemaVersion |
| AnalyzeInputV1 | 用户主题、显式素材和剪辑目标 | inputSchemaVersion |
| TaskSubmissionV1 | Java → Python 的输入快照与执行身份 | protocolVersion |
| TaskEventV1 | 进度、心跳、成功/失败及产物引用 | protocolVersion |

scripts/generate_b1_contracts.py 从 Python 模型生成六份独立 JSON Schema、
script-contract-bundle-v1.schema.json、Java B1TypesV1 records、随 API jar 打包的结构 Schema
及 TypeScript scriptContractsV1.ts。生成命令：

    AgentCut-ai/.venv314/bin/python scripts/generate_b1_contracts.py
    AgentCut-ai/.venv314/bin/python scripts/generate_b1_fixtures.py

生成器不读取 .env、不连接模型、不修改端点。Python 漂移测试检查全部生成文件。
Java B1Structure 只解释本生成器使用的有限 Schema 关键字，遇到新关键字会拒绝，
并非通用 JSON Schema 引擎。前端使用现有 Ajv 2020 校验结构。

**结构 Schema 不能单独证明引用、来源和时间合法。** 完整入口分别为：

- Python：ScriptContractBundleV1.model_validate；
- Java：ScriptContractsV1.parseBundle；
- TypeScript：parseScriptContractBundleV1。

Bundle 为上下文校验提供索引、决策、脚本、提交与已接受事件历史。
它不是新端点，也不要求每个回调携带所有大型文档；B2/B3 应从可信仓储加载对应不可变快照。

## 身份、时间与哈希

- ID 为非空 ASCII 字符串，允许字母、数字、下划线和连字符，禁止数字型 JSON ID。
- 时间使用原视频全局整数毫秒，区间左闭右开；成片使用独立的全局输出时间轴。
- 整数限制为 JavaScript 安全整数范围，禁止布尔值和数字字符串充当时间。
  JSON 数学整数 1.0 与 1 视为同值。
- 所有字段必须出现；可空字段显式为 null。未知字段拒绝。
- revision/indexVersion 为正整数，与 Schema 版本分开。
- 哈希格式为 sha256: 加 64 位小写十六进制。

哈希使用 UTF-8 JSON：对象键按 ASCII 名称排序，数组保留顺序，无多余空白；
Unicode 文本不做归一化，整数以十进制表示，null 与缺失字段不等价。
参与哈希的对象只含字符串、布尔、空值、安全整数及其容器，QA 浮点分数不参与候选哈希。

| 哈希 | 计算范围 |
|---|---|
| indexHash | MaterialIndex 除 indexHash 本身 |
| inputHash | projectId、完整 assetRef、configVersion、input 去掉 requestId |
| scriptHash | EditingScript 去掉 scriptHash、validationReport、quality、reviewStatus |

requestId 用于受理去重；runId/attempt 用于执行身份，两者都不冒充服务商调用幂等。
内容、建议、风险、revision 或索引变化会改变 scriptHash。校验和 QA 必须绑定当前
candidateHash；产物引用同时绑定 artifactId、revision、contentHash。

## MaterialIndex

scenes 必须从 0 连续覆盖到 durationMs，视觉采样预算不能删除源镜头区间。
units 为按源时间排序、互不重叠的可选择单元，可留有尚未形成可选择单元的区间；
不能把单元覆盖率冒充完整镜头索引覆盖率。

transcripts 保存原始 ASR 文本、区间、精度和来源；observations 保存帧 ID、
场景 ID、采样时间、描述及来源。单元引用必须存在并处于对应时间/场景内。
SPEECH 单元取用完整、连续的转写记录；原话由这些记录直接拼接，不允许缩短声学块
或提高其对齐精度。COARSE_BLOCK 只能整体选择，并列出 COARSE_ALIGNMENT 风险。
VISUAL_ONLY 没有原话和转写引用；NO_SPEECH 不能与已知转写矛盾。

依赖区分 REQUIRED 与 REVIEW：删除 REQUIRED 依赖使决策非法；
未选中的 REVIEW 依赖必须记录风险。这里只校验已声明依赖，不能证明模型没有漏报。
转写与视觉事实本身的真实性仍须在 B2 证据生成及人工验收中验证。

## DirectorDecision

每行只含 rowId、sourceUnitRefs、narrativeRole、selectionReason 和包装建议。
禁止自由源时间、原话、媒体路径和执行指令。单元不可重复选择或重排。
同一行只允许合并连续完整单元，不连续区间必须拆行。
indexRef 和 inputHash 必须绑定当前输入与索引，旧引用不能静默映射到新素材。

## EditingScript

| 列 | 字段与校验 |
|---|---|
| 镜号 | shotNo 从 1 连续编号；rowId 与决策一致 |
| 成片时间 | outputRange 从 0 连续累计，原速硬切，无隐式重叠 |
| 原素材入点—出点 | sourceParts 精确复制完整单元的 sourceRange |
| 画面 | visualEvidence 精确引用索引观察；treatmentNote 另列建议 |
| 原声／声音 | spokenQuotes 精确取索引原文；audioTreatment 固定 ORIGINAL |
| 字幕与包装 | captionCues 使用输出全局时间；包装建议独立留存 |
| 剪辑备注 | narrativeRole、selectionReason、dependencyRefs、riskRefs、cutNotes |

estimatedDurationMs 等于累计时长且不超过 maxDurationMs；desiredDurationMs 只是偏好，
允许实际计划更短，不加速或补编内容填满。

字幕只允许 REAL 且有 SENTENCE/WORD/MANUAL 对齐的整条转写单元。
删除前段后字幕必须重算输出时间，不能复制源时间。字幕请求未满足时列出
SUBTITLE_UNAVAILABLE 风险。未来投影到 OpSubtitle 还需减去行 outputStartMs，
转换为段内输出时间；本批不提供编译器。

可执行动作只允许 ORIGINAL_AUDIO 与 CAPTION，每行原声、每个字幕 cue 各有一次对应动作。
标题、动画、B-roll、音乐等为人工建议，状态为 PROPOSED、ACCEPTED_MANUAL 或 REJECTED。
当前没有包装编译器，本版本拒绝 COMPILED；接受建议不等于执行完成。

READY 要求硬校验通过、无未解风险、来源合格且当前候选的 QA 通过。
缺 QA、模拟来源、缺视觉、粗对齐或未满足字幕须显式列风险并保留为需复核草稿。
硬错误不能通过成功结果发布，QA 分数不能覆盖硬门禁。
CONFIRMED 状态及执行确认留给 B5 的绑定快照协议。

## 任务协议

用户输入显式提供 assetId、taskName、requestId 和 target：主题、模式、硬时长、
期望时长、画幅、字幕、风格、内容类型及原序原速硬切策略。
内部提交增加 projectId/taskId/runId/attempt/configVersion/inputHash、
assetRef、mediaObjectKey 和服务端构造的 callbackUrl。
mediaObjectKey 拒绝绝对路径、空路径段或点/父目录段。
对象归属、文件完整性、URL 目的地及权限仍由 B3 服务端准入检查。

事件身份必须与提交一致；sequence 前进，progress 单调。
心跳可在进度不变时更新，heartbeatAt 为精确到秒的有效 UTC 日历时间。
phase 为 VALIDATING_INPUT、PROBING、TRANSCRIBING、VISUAL_ANALYZING、
INDEXING、PLANNING、CHECKING、PERSISTING、COMPLETED 或 FAILED。

| 事件/结果 | 约束 | 兼容现有任务终态 |
|---|---|---|
| PROGRESS | RUNNING，progress < 100，无结果和错误 | 非终态 |
| COMPLETED + SUCCESS + READY | 完整结果、当前合格脚本引用、无错误 | SUCCESS |
| COMPLETED + SUCCESS + NEEDS_REVIEW | 合法草稿及风险；PARTIAL 必须需复核 | NEEDS_REVIEW |
| COMPLETED + FAILED | error 必填，无正常产物，reviewStatus=NOT_AVAILABLE | FAILED |

100% 只能在接收端校验并原子提交结果后对外发布。旧 attempt、重复、乱序及终态后事件
不得推进任务。校验器检查的是已经接受的历史，会拒绝含这些事件的历史；
实际接收端的去重、忽略晚到和原子提交由 B3 接入，本批不改旧状态机。

错误分类：INVALID_INPUT、UNSUPPORTED_INPUT、CONSTRAINT_CONFLICT、NO_CANDIDATE、
MODEL_TIMEOUT、MODEL_FAILED、VALIDATION_FAILED、CAPACITY_EXCEEDED、
INTERNAL_ERROR、SUBMISSION_UNCERTAIN，另有 message/retryable。
NO_CANDIDATE 表示有限搜索未找到；CONSTRAINT_CONFLICT 需要硬约束冲突证据。
retryable 不自动授权再次调用模型；受理不确定时须以相同 runId 协调。

## 离线验收

script-contracts-v1.fixtures.json 为三端唯一共享样例。它保存基础文档与逐项变更，
覆盖可信结果、NO_SPEECH、模拟/部分失败/缺 QA 草稿、跨镜头转写、
源前段删除后的输出字幕、包装建议、失败无假脚本，以及非法引用/时间/版本/回调。

    cd AgentCut-ai
    AGENTCUT_LOAD_DOTENV=false AGENTCUT_AI_SIMULATE=true AGENTCUT_VLM_API_KEY='' AGENTCUT_LLM_API_KEY='' .venv314/bin/python -m pytest tests -q

    cd ../AgentCut-backend
    JAVA_HOME=/opt/homebrew/opt/openjdk@17 mvn -o test

    cd ../AgentCut-front
    npm run test:contracts
    npm test
    npm run build

现有 AnalysisEvidence 1.0 和 Plan 1.0 保持原契约。
下一批 B2a-1 实现完整源索引、自适应窗口与 ASR/VLM 时间融合。
