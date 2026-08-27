"""AgentCut 分析服务入口。

挂载业务路由（POST /analyze、GET /analyze/{jobId}/status 等）。
运行：cd AgentCut-ai && uvicorn app.main:app --reload
"""

from fastapi import FastAPI

from app.api.analyze import router as analyze_router

app = FastAPI(
    title="AgentCut-AI",
    version="0.1.0",
    description="AgentCut 视频分析服务（Python + LangChain）：抽帧 → 场景 → ASR → VLM → 方案生成",
)

# 业务路由（analyze.py 内已带 /analyze 前缀，直接挂载）
app.include_router(analyze_router)


@app.get("/health")
def health() -> dict:
    """健康检查。"""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
