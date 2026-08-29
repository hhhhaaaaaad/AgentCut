# AgentCut 多 Agent 剪辑脚本架构设计

> 目标：把项目从「单次 LLM 直出剪辑方案」升级为「多 Agent 协同 + 质量监督」，核心诉求是**提升剪辑脚本质量**。
>
> 一个「视频剪辑分析师」分析视频的时间点与讲解内容，其余 Agent 负责分析与质量监督，共同产出一份高质量剪辑方案脚本。

---

## 0. 结论先行

脚本质量的瓶颈不在「有没有 Agent」，而在缺了三样东西：

1. **专家拆解** —— 「视频剪辑分析师」该干的活（分析时间点、分析讲解内容）目前被一个 VLM 调用一次性糊出来，没有专门的时间轴分析师、没有专门的讲解内容分析师。
2. **质检闭环** —— 方案生成是一次 `invoke` 就交付，没有「审查 → 打分 → 重写」的监督循环。生成即定稿，错了没人纠。
3. **确定性校验闸** —— 目前只有 Pydantic 字段校验（`plan.py` 只查 transition 引用），没有「时间轴连续性 / 裁剪坐标越界 / 变速后成片时长 / 字幕-口播匹配」这些语义级校验。

多 Agent 架构，本质就是补这三样。

---

## 1. 现状诊断（对着代码说）

### 1.1 理解层：`AnalysisAgent` + `vlm_understand.py` —— 「剪辑分析师」目前并不存在

当前流水线（`analysis_agent.py:run`）：抽帧 → 场景 → ASR → **一次 VLM** → 组装。问题在于那「一次 VLM」：

1. **一个调用混了 6 种职责**。`vlm_understand._build_understanding_prompt` 要求 VLM 一次输出 `summary / sceneDescriptions / sceneTags / sceneImportance / highlights / suggestions` 六个字段——等于让一个模型同时当「时间轴分析师 + 讲解内容分析师 + 画面分析师 + 剪辑建议师」。职责越混，每个字段越浅、越不稳（历史上因此出现过 `sceneImportance` 标量/列表不一致、JSON 截断等坑）。

2. **「讲解内容」分析名存实亡**。`vlm_understand` 里 transcript 被**截断到 800 字符**才喂给 VLM；而 `transcribe.py` 已用 VAD + Qwen3-ASR 拿到了**带真实时间戳的全文转写**。最值钱的「视频在讲什么」这份完整语义，被 800 字符截断毁了。

3. **时间点与画面没有对齐/交叉验证**。ASR 产出真实时间戳，场景检测产出镜头边界，但两条时间轴没有合并——VLM 只看到抽帧 + 一段截断文字，并不知道「第 3 个镜头在讲 X 论点，第 5 个镜头是空话」。

### 1.2 方案层：`PlanAgent` —— 脚本质量的核心短板全在这

1. **单次直出，零质检**。`_build_with_llm` 就是 `prompt → invoke → model_validate` 三步结束，没有「这份方案好不好」的评估。

2. **只有字段校验，没有语义校验**。`Plan.model_validator` 只检查 transition 引用。它**不检查**：
   - `sourceRange` 的 start/end 是否越界（LLM 可能写出 end > 源时长）
   - 相邻 segment 时间轴是否重叠/乱序
   - `OpCrop` 的裁切坐标是否超出源像素
   - 变速后 `subtitle.end` 是否对得上成片时长
   - `keep=false` 的片段是否还残留 subtitle/speed 操作

3. **VLM 报告 → LLM 方案的语义断层**。VLM 给的 `highlights`（该保留）/ `suggestions`（该删）/ `importance`（重要性），在 `_build_prompt` 里只是作为 JSON 文本**平铺**给 DeepSeek，没有强制约束。LLM 可自由发挥、忽略这些信号，从零重写 timeline——「分析」与「剪辑」之间是断的。

4. **时长/节奏是粗暴规则，不是语义决策**。`_apply_duration_constraint` 就是：变速到 2.5，还超就丢 `importance` 最低的片段。它不知道「这段是核心论点不能删」「那段是废话可以砍」，只按浮点数排序。

5. **没有「内容完整性」视角**。方案可能把最关键的一段讲解当低重要性场景删掉，却没有 agent 回头检查「讲的核心内容还在不在」。

---

## 2. 多 Agent 目标架构

```
                        分析域（3 个专家，各司其职）
   ┌──────────────────────────────────────────────────────────┐
   │ ① 时间轴分析师        ② 讲解内容分析师        ③ 视觉分析师      │
   │  Timeline Analyst    Narration Analyst     Visual Analyst │
   │  输入: 场景边界+ASR时间戳 输入: ASR全文(不截断)  输入: 关键帧      │
   │       +静音区间       输出: 主题/论点/关键句/   输出: 每场景画面语义│
   │  输出: 章节/节奏/废话区间    冗余/情绪强调点      +重要性/是否值得留 │
   │  模型: 规则+LLM        模型: LLM(DeepSeek)    模型: VLM(Qwen-VL)│
   └────────────────┬─────────────────────────────────────────┘
                    ▼
        ④ 视频剪辑分析师 (Editing Director / 主规划)
        输入: 三个专家产出 + 用户 target
        输出: 初版 Plan（keep/delete/speed/crop/subtitle/transition）
        模型: LLM(DeepSeek)

                    ▼
        ⑤ 质量监督 Agent (QA Reviewer)   ←── 脚本质量的核心
        输入: 初版 Plan + 三个专家产出 + target
        输出: 分维度评分 + 问题清单(每项带 sceneIndex/原因)
        模型: LLM(DeepSeek)，输出严格结构化

                    ▼  不达标 & 未超迭代上限 → 回 ④ 重写
        ⑥ 确定性校验闸 (Deterministic Validator，纯代码，非 LLM)
        检查: 时间轴连续性 / 裁剪坐标 / 变速后时长 / 字幕-口播匹配 / 引用合法
        —— 任何 LLM 输出都过这一关，保证「可执行」
```

**关键设计点**：监督用「结构化的分维度打分 + 问题清单」驱动重写，而不是让 QA 自己改方案（避免 QA 又引入新错）。QA 只负责「挑错」，④ 负责「改」。

---

## 3. 质量监督闭环（脚本质量核心）

### 3.1 QA Reviewer 输出结构

QA 输出应为结构化 JSON（对齐新 schema，例如 `QualityReview`）：

```jsonc
{
  "overallScore": 0.72,          // 0~1，低于阈值触发重写
  "passed": false,
  "issues": [
    {
      "dimension": "timeline_continuity",   // 见下表
      "severity": "high",                    // high / medium / low
      "sceneIndex": 3,
      "reason": "片段 seg_003 与 seg_004 时间轴重叠 0.8s",
      "suggestion": "将 seg_004.sourceRange.start 调整为 seg_003.end"
    }
  ]
}
```

### 3.2 监督维度

| 维度 | 检查什么 | 为什么重要 |
|---|---|---|
| `timeline_continuity` | 时间轴连续、无重叠、无越界、顺序正确 | 不连续 → FFmpeg 出错/跳帧 |
| `content_integrity` | 讲解分析师标的核心论点/关键句，成片里是否都保留 | 避免「剪掉重点」 |
| `pacing` | 目标时长达成、变速 ≤2.5、无过度删减或拖沓 | 落实 maxDuration 约束 |
| `narration_visual_match` | 字幕文本与口播一致、画面与讲解对得上 | 字幕错位、图文不符 |
| `executability` | crop 坐标合法、speed>0、transition 引用存在 | 保证 render 不 500 |

### 3.3 迭代循环

`④ 生成 → ⑤ 评分 → 不达标则把 issue 清单喂回 ④ 重写 → 再评`，直到 `overallScore ≥ 阈值`（如 0.85）或达最大迭代次数（如 2~3 轮，控制成本）。**最后一次重写后无论分数如何都要过 ⑥ 校验闸**，过了就交付，过不了就回退到确定性规则方案（`_build_deterministic` 那套，它永远合法）。

### 3.4 兜底策略

多 Agent 意味着更多次模型调用、更多失败点，每层都要降级：

- ③ 视觉分析师 VLM 挂了 → 场景描述留空 + importance 默认 0.5（沿用 `_normalize_understanding` 兜底思路）
- ⑤ QA 挂了 → 跳过监督，直接进 ⑥ 校验闸（闸是纯代码，不依赖模型，永远在）
- ④ 重写 N 次仍不达标 → 取历史最高分那版，过 ⑥ 后交付

---

## 4. 分阶段落地步骤

### Phase 1 — 把「一次 VLM」拆成三个专家（改理解层，风险最低）

- 新增 `app/agents/timeline_agent.py`、`narration_agent.py`、`visual_agent.py`
- `timeline_agent` 主要靠规则（场景边界 + 静音 + ASR 密度），LLM 只做「章节切分」轻活
- `narration_agent` 吃**完整 transcript**（去掉 800 字符截断），LLM 抽取主题/论点/关键句/冗余
- `visual_agent` = 现在 `vlm_understand` 的视觉部分，但只输出「每场景画面语义 + 重要性」
- 改 `analysis_agent.py` 编排：三个专家产出后 `_assemble` 汇总成扩展后的 `AnalysisReport`
- 收益：输入质量立刻提升，尤其是「讲解内容」从无到有

### Phase 2 — 加质检闭环（改方案层，脚本质量核心）

- 新增 `app/agents/quality_agent.py`（QA Reviewer，输出结构化 `QualityReview`）
- 新增 `app/schemas/quality.py`（`QualityReview` / `QualityIssue` 模型）
- 改 `plan_agent.py`：`_build_with_llm` 包一层循环 `生成 → QA 评分 → 带 issue 重写`
- 新增 `app/agents/validator.py`（⑥ 确定性校验闸，纯代码）——本次最能「保底」的一块，独立可测
- 收益：方案质量从「碰运气」变成「有兜底、可迭代」

### Phase 3 — 接回 Java 侧 + 结构化信号强制（打通 + 消除语义断层）

- `analyze.py` 的 `result` 里把 QA 的评分/问题清单也带出去，Java 端能在「方案文档」里展示「质检报告」（面试可演示的亮点）
- 让 ④ 的 prompt 不再平铺 VLM 报告，而是把 `highlights` 作为「必须保留」、`suggestions(type=delete)` 作为「必须删除」的**硬约束**注入，消除语义断层
- 可选：给 `TargetConstraints` 加 `qualityThreshold` 字段，让「脚本质量」成为用户可感知的配置项

---

## 5. 风险与权衡

1. **成本/延迟**：从「2 次模型调用」变成「3 专家 + 导演 + N 次 QA」（约 5~8 次），延迟可能从秒级到分钟级。
   - 对策：专家层只 ② ③ 用模型、① 用规则；QA 迭代上限 2 轮；`SIMULATE` 模式仍全走确定性路径。

2. **schema 稳定性**：QA 输出结构化 JSON 会踩和现在 `Plan` 一样的坑（字段漂移）。
   - 对策：复用 `Plan` 已有的 `json.dumps(model_json_schema())` 注入手法，QA 的 schema 也用 Pydantic `model_validate` 硬校验 + 失败降级（跳过监督）。

3. **多模型一致性**：VLM 和 LLM 对「场景重要性」的判断可能打架。
   - 对策：QA 的 `content_integrity` 维度以 ② 讲解分析师（LLM）的判断为准，`visual` 只做参考。

4. **不要过度工程**：三个专家如果每个都写得像 PlanAgent 那么重，维护成本会爆。
   - 对策：专家层薄一点，只输出各自单一的结构化产物，真正的「融合 + 决策」集中在 ④ 一个导演 agent。

---

## 6. 建议的下一步

- 从 **Phase 2 的「确定性校验闸」** 和 **Phase 1 的「讲解内容分析师」** 先动手——它们最能直接提升「脚本质量」，且独立、可测、风险低。
- 待方向确认后，可将本文拆成更细的 `docs/` 实现文档（含每个新 schema 的字段定义、每个 agent 的 prompt 模板、校验闸的规则清单）。
