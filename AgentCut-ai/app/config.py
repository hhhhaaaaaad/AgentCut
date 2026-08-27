"""全局配置：模型接入（DashScope OpenAI 兼容端点） + 模拟模式开关。

默认使用 Qwen2.5-VL，走阿里 DashScope 的 OpenAI 兼容端点，
LangChain 可直接用 ChatOpenAI / OpenAI 客户端接入。
切换其他模型（Gemini / GPT-4o / Claude）只需修改 BASE_URL / API_KEY / MODEL，不改代码。

模拟模式（AGENTCUT_AI_SIMULATE）：
  无真实 API Key 或显式开启时，tools / agents 返回占位数据，
  保证服务可端到端跑通（不依赖外部模型与本地视频）。
"""

import os

# DashScope OpenAI 兼容端点（可通过环境变量覆盖）
BASE_URL = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

# API Key 从环境变量读取（占位，未设置时为空字符串）
API_KEY = os.getenv("DASHSCOPE_API_KEY", "")

# 默认视频理解模型
MODEL = os.getenv("AGENTCUT_AI_MODEL", "qwen2.5-vl")

# 分析任务超时（秒），可通过环境变量覆盖
TIMEOUT_SECONDS = int(os.getenv("AGENTCUT_AI_TIMEOUT", "300"))

# 工作目录（帧图 / 临时文件），默认 AgentCut-ai/work
WORK_DIR = os.getenv(
    "AGENTCUT_AI_WORK_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "work"),
)

# 模拟模式：显式设置时以其为准；否则无 API Key 时默认开启模拟
_SIMULATE_FLAG = os.getenv("AGENTCUT_AI_SIMULATE")
if _SIMULATE_FLAG is not None:
    SIMULATE = _SIMULATE_FLAG.strip().lower() in ("1", "true", "yes", "on")
else:
    SIMULATE = not API_KEY


def get_openai_client():
    """构造 OpenAI 兼容 SDK 客户端（DashScope，可替换任意兼容端点）。

    复用本模块的 BASE_URL / API_KEY / TIMEOUT_SECONDS，避免重复定义。
    """
    from openai import OpenAI

    return OpenAI(base_url=BASE_URL, api_key=API_KEY, timeout=TIMEOUT_SECONDS)


def get_langchain_chat_model(temperature: float = 0.2):
    """构造 LangChain ChatOpenAI（结构化输出 / 工具调用路径用）。

    未配置 API Key 或未安装 langchain-openai 时返回 None，由调用方降级到确定性方案。
    """
    if not API_KEY:
        return None
    try:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            base_url=BASE_URL,
            api_key=API_KEY,
            model=MODEL,
            temperature=temperature,
            timeout=TIMEOUT_SECONDS,
        )
    except Exception:
        return None
