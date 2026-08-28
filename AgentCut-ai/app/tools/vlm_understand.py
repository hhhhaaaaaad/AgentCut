"""Qwen3-VL 多模态理解工具（app.tools.vlm_understand）。

走 SiliconFlow OpenAI 兼容端点（复用 config.VLM_BASE_URL / VLM_API_KEY / VLM_MODEL），
用 OpenAI SDK 客户端构造多模态消息（本地帧图 base64 内联）。
缺 key / 模拟模式下返回确定性占位理解结果。
"""

import base64
import json
import logging
import mimetypes
from threading import Lock
from typing import Optional, Sequence

from app import config

logger = logging.getLogger(__name__)

# 重型依赖可选：缺失时进入模拟模式
try:  # pragma: no cover - 依赖缺失时的降级路径
    from openai import OpenAI

    _HAS_OPENAI = True
except Exception as exc:  # pragma: no cover
    OpenAI = None
    _HAS_OPENAI = False
    logger.warning("openai SDK 未安装，VLM 理解进入模拟模式：%s", exc)

_client = None
_client_lock = Lock()


def get_client():
    """懒加载 OpenAI 兼容客户端（复用 config 的 BASE_URL / API_KEY）。"""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = config.get_openai_client()
    return _client


def _frame_to_data_url(frame_path: str) -> str:
    """把本地帧图编码为 data URL（Qwen2.5-VL 经 DashScope 支持内联图片）。"""
    with open(frame_path, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode("ascii")
    mime = mimetypes.guess_type(frame_path)[0] or "image/jpeg"
    return f"data:{mime};base64,{b64}"


def _build_messages(prompt: str, frame_paths: Sequence[str]) -> list:
    """构造 OpenAI 兼容多模态消息（text + image_url）。"""
    content: list = [{"type": "text", "text": prompt}]
    for fp in frame_paths:
        content.append({"type": "image_url", "image_url": {"url": _frame_to_data_url(fp)}})
    return [{"role": "user", "content": content}]


def understand_frames(prompt: str, frame_paths: Sequence[str]) -> str:
    """把若干帧图 + 提示词交给 Qwen2.5-VL，返回文本回复。"""
    if config.SIMULATE_FORCED or not _HAS_OPENAI or not config.VLM_API_KEY:
        return _simulate_frames_reply(prompt, frame_paths)
    client = get_client()
    resp = client.chat.completions.create(
        model=config.VLM_MODEL,
        messages=_build_messages(prompt, frame_paths),
        temperature=0.2,
        max_tokens=8192,
    )
    return resp.choices[0].message.content or ""


def _build_understanding_prompt(scenes, transcripts, meta) -> str:
    """构造"整片理解"提示词，要求模型只输出 JSON。"""
    scene_overview = "\n".join(
        f"- 场景{i}: {sc.start:.1f}s~{sc.end:.1f}s" for i, sc in enumerate(scenes)
    )
    transcript_text = "\n".join(
        f"[{t.start:.1f}s-{t.end:.1f}s] {t.text}" for t in transcripts
    )
    return (
        "你是视频内容分析助手。请基于以下场景时间线与语音转写，判断每个场景的内容、重要度，"
        "并给出剪辑建议。\n"
        f"视频元数据: {meta}\n"
        f"场景列表:\n{scene_overview}\n"
        f"语音转写:\n{transcript_text}\n"
        '只输出 JSON，格式: '
        '{"summary":"...","sceneDescriptions":["..."],"sceneTags":[["..."]],'
        '"sceneImportance":[0~1],"highlights":[{"sceneIndex":0,"start":0.0,"end":1.0,'
        '"reason":"..","score":0.8}],'
        '"suggestions":[{"type":"keep|delete|speed|crop|subtitle|volume|mute",'
        '"sceneIndex":0,"reason":"..","params":{}}]}'
    )


def understand_video(scenes, frames, transcripts, meta) -> dict:
    """综合分析视频（场景帧 + 转写），产出结构化理解结果 dict。

    真实路径：帧图 + 提示词 → Qwen2.5-VL → 解析 JSON；
    模拟 / 无帧 / 解析失败：回退到确定性占位理解。
    """
    if config.SIMULATE_FORCED or not _HAS_OPENAI or not config.VLM_API_KEY or not frames:
        return _simulate_understanding(scenes, transcripts, meta)
    prompt = _build_understanding_prompt(scenes, transcripts, meta)
    reply = understand_frames(prompt, frames)
    try:
        cleaned = reply.strip().removeprefix("```json").removesuffix("```").strip()
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return _normalize_understanding(data, scenes)
    except Exception as exc:
        logger.warning("VLM 返回非 JSON，回退为模拟理解：%s", exc)
    return _simulate_understanding(scenes, transcripts, meta)


def _normalize_understanding(data: dict, scenes) -> dict:
    """把 VLM 返回的字段归一化为 list（单场景时 VLM 可能返回标量而非数组）。"""
    n = len(scenes)
    for key, default in (("sceneDescriptions", ""), ("sceneImportance", 0.5)):
        val = data.get(key, [])
        if not isinstance(val, list):
            val = [default] if val is None else [val]
        while len(val) < n:
            val.append(default)
        data[key] = val[:n]
    # sceneTags 期望 list-of-list
    tags = data.get("sceneTags", [])
    if not isinstance(tags, list):
        tags = [[tags]] if tags else []
    elif tags and not isinstance(tags[0], list):
        tags = [[t] for t in tags]
    while len(tags) < n:
        tags.append([])
    data["sceneTags"] = tags[:n]
    return data


def _simulate_frames_reply(prompt: str, frame_paths) -> str:
    """模拟 VLM 帧图回复（占位）。"""
    return f"[模拟 VLM] 已分析 {len(frame_paths)} 张帧图。prompt 摘要: {prompt[:80]}..."


def _simulate_understanding(scenes, transcripts, meta) -> dict:
    """确定性占位理解：基于转写构造场景描述 / 亮点 / 建议。"""
    scene_desc: list = []
    scene_tags: list = []
    scene_importance: list = []
    for sc in scenes:
        text = " ".join(
            t.text for t in transcripts if t.start < sc.end and t.end > sc.start
        ).strip()
        scene_desc.append(text if text else f"场景 {sc.start:.1f}s~{sc.end:.1f}s（无明显语音内容）")
        scene_tags.append(["口播"] if text else ["空镜"])
        scene_importance.append(0.9 if text else 0.3)

    # 亮点：重要度最高的前两个场景
    ranked = sorted(range(len(scenes)), key=lambda i: scene_importance[i], reverse=True)
    highlights = []
    for idx in ranked[:2]:
        sc = scenes[idx]
        highlights.append(
            {
                "sceneIndex": idx,
                "start": sc.start,
                "end": sc.end,
                "reason": (scene_desc[idx][:60] + "（语义重点）") if idx < len(scene_desc) else "重点内容",
                "score": scene_importance[idx],
            }
        )
    suggestions = [
        {"type": "keep", "sceneIndex": ranked[0], "reason": "核心内容，建议保留", "params": {}},
        {"type": "keep", "sceneIndex": ranked[1], "reason": "亮点片段，建议保留", "params": {}},
        {"type": "delete", "sceneIndex": ranked[-1], "reason": "重要性低，可考虑删除", "params": {}},
        {"type": "subtitle", "sceneIndex": None, "reason": "建议全片添加字幕提升可读性", "params": {}},
    ]
    return {
        "summary": "这是一个口播类视频，围绕主题依次展开，中段为重点讲解部分。",
        "sceneDescriptions": scene_desc,
        "sceneTags": scene_tags,
        "sceneImportance": scene_importance,
        "highlights": highlights,
        "suggestions": suggestions,
        "notes": "模拟理解（未调用真实 VLM）",
        "simulated": True,
    }
