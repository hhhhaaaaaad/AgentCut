"""AgentCut 分析服务包。

子包划分（对齐整体设计方案）：
- app.api      外部 HTTP 接口
- app.agents   LangChain agent（AnalysisAgent / PlanAgent）
- app.tools    确定性工具（抽帧/场景检测/ASR/VLM）
- app.schemas  Pydantic 模型（与 docs/plan-schema.json 对齐）
"""
