"""全局配置：双模型端点（SiliconFlow VLM + DeepSeek LLM） + 模拟模式开关。

- 视频理解（VLM）：SiliconFlow 的 Qwen3-VL-8B-Instruct（多模态，看视频帧）
- 方案生成（LLM）：DeepSeek 的 deepseek-v4-pro（纯文本，结构化输出）
两端点均 OpenAI 兼容，VLM 用 openai SDK，LLM 用 LangChain ChatOpenAI。

切换任意模型只需修改对应的 BASE_URL / API_KEY / MODEL 环境变量，不改代码。

模拟模式（AGENTCUT_AI_SIMULATE）：
  无真实 API Key 或显式开启时，tools / agents 返回占位数据，
  保证服务可端到端跑通（不依赖外部模型与本地视频）。
"""

import os

# 加载项目根目录的 .env（若存在），便于本地配置 API Key（无第三方依赖）
def _load_dotenv():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

_load_dotenv()

# ---------- VLM：视频理解（SiliconFlow） ----------
VLM_BASE_URL = os.getenv("AGENTCUT_VLM_BASE_URL", "https://api.siliconflow.cn/v1")
VLM_API_KEY = os.getenv("AGENTCUT_VLM_API_KEY", "")
VLM_MODEL = os.getenv("AGENTCUT_VLM_MODEL", "Qwen/Qwen3-VL-8B-Instruct")

# ---------- ASR：语音转写（SiliconFlow，复用 VLM 端点与 key） ----------
ASR_MODEL = os.getenv("AGENTCUT_ASR_MODEL", "FunAudioLLM/SenseVoiceSmall")

# ---------- LLM：方案生成（DeepSeek） ----------
LLM_BASE_URL = os.getenv("AGENTCUT_LLM_BASE_URL", "https://api.deepseek.com")
LLM_API_KEY = os.getenv("AGENTCUT_LLM_API_KEY", "")
LLM_MODEL = os.getenv("AGENTCUT_LLM_MODEL", "deepseek-v4-pro")

# 分析任务超时（秒），可通过环境变量覆盖
TIMEOUT_SECONDS = int(os.getenv("AGENTCUT_AI_TIMEOUT", "300"))

# 工作目录（帧图 / 临时文件），默认 AgentCut-ai/work
WORK_DIR = os.getenv(
    "AGENTCUT_AI_WORK_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "work"),
)

# 模拟开关：
# - SIMULATE_FORCED：用户显式设置 AGENTCUT_AI_SIMULATE（True 强制模拟 / False 强制真实 / None 自动判断）
# - SIMULATE：向后兼容的全局便捷开关（未显式设置时，两个 key 缺一即模拟）
_SIMULATE_FLAG = os.getenv("AGENTCUT_AI_SIMULATE")
if _SIMULATE_FLAG is not None:
    SIMULATE_FORCED = _SIMULATE_FLAG.strip().lower() in ("1", "true", "yes", "on")
else:
    SIMULATE_FORCED = None

SIMULATE = (
    SIMULATE_FORCED
    if SIMULATE_FORCED is not None
    else not (VLM_API_KEY and LLM_API_KEY)
)


def get_openai_client():
    """构造 VLM 的 OpenAI 兼容客户端（SiliconFlow）。

    未配置 VLM_API_KEY 时返回 None（openai 3.x 对空 key 会抛异常，这里显式兜底）。
    """
    if not VLM_API_KEY:
        return None
    from openai import OpenAI

    return OpenAI(base_url=VLM_BASE_URL, api_key=VLM_API_KEY, timeout=TIMEOUT_SECONDS, max_retries=3)


def get_langchain_chat_model(temperature: float = 0.2):
    """构造 LLM 的 LangChain ChatOpenAI（DeepSeek，结构化输出路径用）。

    未配置 LLM_API_KEY 或未安装 langchain-openai 时返回 None，由调用方降级到确定性方案。
    """
    if not LLM_API_KEY:
        return None
    try:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            base_url=LLM_BASE_URL,
            api_key=LLM_API_KEY,
            model=LLM_MODEL,
            temperature=temperature,
            timeout=TIMEOUT_SECONDS,
        )
    except Exception:
        return None
