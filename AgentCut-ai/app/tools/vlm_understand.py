"""Qwen3-VL 多模态理解工具（app.tools.vlm_understand）。

走 SiliconFlow OpenAI 兼容端点（复用 config.VLM_BASE_URL / VLM_API_KEY / VLM_MODEL），
用 OpenAI SDK 客户端构造多模态消息（本地帧图 base64 内联）。
缺 key / 模拟模式下返回确定性占位理解结果。
"""

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
import mimetypes
import re
from threading import Lock
import time
from typing import Sequence

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


def _build_messages(
    prompt: str,
    frame_paths: Sequence[str],
    detail: str = "low",
) -> list:
    """构造 OpenAI 兼容多模态消息（text + image_url）。"""
    content: list = [{"type": "text", "text": prompt}]
    for fp in frame_paths:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": _frame_to_data_url(fp), "detail": detail},
            }
        )
    return [{"role": "user", "content": content}]


def understand_frames(
    prompt: str,
    frame_paths: Sequence[str],
    *,
    detail: str | None = None,
    timeout: float | None = None,
) -> str:
    """把若干帧图 + 提示词交给 Qwen2.5-VL，返回文本回复。"""
    if config.SIMULATE_FORCED or not _HAS_OPENAI or not config.VLM_API_KEY:
        return _simulate_frames_reply(prompt, frame_paths)
    client = get_client()
    resp = client.chat.completions.create(
        model=config.VLM_MODEL,
        messages=_build_messages(
            prompt,
            frame_paths,
            detail=detail or config.VLM_IMAGE_DETAIL,
        ),
        temperature=0.2,
        max_tokens=config.VLM_BATCH_MAX_TOKENS,
        timeout=timeout or config.VLM_BATCH_TIMEOUT_SECONDS,
    )
    return resp.choices[0].message.content or ""


class _InvalidBatchResult(ValueError):
    """VLM 批次返回无法安全映射到输入场景。"""


def _frame_scene_index(frame_path: str, fallback_index: int) -> int:
    """从抽帧文件名恢复原场景索引；非标准路径保持旧的按位置映射。"""
    match = re.search(r"(?:^|[\\/])scene_(\d+)_", frame_path)
    return int(match.group(1)) if match else fallback_index


def _index_frames(scenes, frames) -> tuple[list[dict], list[int]]:
    """建立帧到旧 AnalysisReport 全局场景索引的稳定映射。"""
    indexed: list[dict] = []
    seen: set[int] = set()
    for position, frame_path in enumerate(frames):
        scene_index = _frame_scene_index(frame_path, position)
        if scene_index < 0 or scene_index >= len(scenes) or scene_index in seen:
            logger.warning(
                "忽略无法映射的 VLM 帧: path=%s sceneIndex=%s",
                frame_path,
                scene_index,
            )
            continue
        seen.add(scene_index)
        indexed.append(
            {
                "sceneIndex": scene_index,
                "scene": scenes[scene_index],
                "framePath": frame_path,
            }
        )
    indexed.sort(key=lambda item: item["sceneIndex"])
    missing = [i for i in range(len(scenes)) if i not in seen]
    return indexed, missing


def _related_transcripts(items: Sequence[dict], transcripts) -> list:
    scene_ranges = [(item["scene"].start, item["scene"].end) for item in items]
    return [
        transcript
        for transcript in transcripts
        if any(
            transcript.start < scene_end and transcript.end > scene_start
            for scene_start, scene_end in scene_ranges
        )
    ]


def _build_batch_prompt(items: Sequence[dict], transcripts, meta) -> str:
    """构造只分析当前批次的提示词，所有索引和时间均沿用整片坐标。"""
    scene_overview = "\n".join(
        f"- 图片{image_no} -> sceneIndex={item['sceneIndex']}, "
        f"time={item['scene'].start:.3f}s~{item['scene'].end:.3f}s"
        for image_no, item in enumerate(items, start=1)
    )
    transcript_text = "\n".join(
        f"[{t.start:.3f}s-{t.end:.3f}s] {t.text}" for t in transcripts
    )
    if len(transcript_text) > 3000:
        transcript_text = transcript_text[:3000] + "...(本批相关转写已截断)"
    safe_meta = {
        key: meta.get(key)
        for key in ("duration", "width", "height", "fps")
        if key in meta
    }
    return (
        "你是视频局部视觉分析助手。只分析本批图片对应的场景，不生成整片结论、剪辑方案、"
        "高光或操作建议。sceneIndex 和时间来自原视频全局坐标，必须原样返回，禁止改成"
        "批内 0 开始的索引。\n"
        f"视频元数据: {safe_meta}\n"
        f"本批场景与图片映射:\n{scene_overview}\n"
        f"仅供本批理解的相关转写:\n{transcript_text or '(无相关转写)'}\n"
        "每个输入 sceneIndex 必须且只能返回一次。description 用一句话描述画面，tags 为"
        "简短字符串数组，importance 为 0 到 1。只输出 JSON："
        '{"batchSummary":"本批局部摘要","scenes":[{"sceneIndex":12,'
        '"description":"...","tags":["..."],"importance":0.8}]}'
    )


def _clean_json_reply(reply: str) -> dict:
    cleaned = reply.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise _InvalidBatchResult("顶层结果不是 JSON object")
    return data


def _parse_batch_reply(reply: str, expected_indices: Sequence[int]) -> dict:
    data = _clean_json_reply(reply)
    raw_scenes = data.get("scenes")
    if not isinstance(raw_scenes, list):
        raise _InvalidBatchResult("缺少 scenes 数组")

    expected = set(expected_indices)
    observations: dict[int, dict] = {}
    for raw in raw_scenes:
        if not isinstance(raw, dict) or isinstance(raw.get("sceneIndex"), bool):
            raise _InvalidBatchResult("场景记录或 sceneIndex 非法")
        try:
            scene_index = int(raw["sceneIndex"])
        except (KeyError, TypeError, ValueError) as exc:
            raise _InvalidBatchResult("sceneIndex 非整数") from exc
        if scene_index not in expected:
            raise _InvalidBatchResult(f"返回未知 sceneIndex={scene_index}")
        if scene_index in observations:
            raise _InvalidBatchResult(f"重复 sceneIndex={scene_index}")

        description = raw.get("description", "")
        tags = raw.get("tags", [])
        importance = raw.get("importance", 0.5)
        if not isinstance(description, str):
            raise _InvalidBatchResult(f"sceneIndex={scene_index} description 非字符串")
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise _InvalidBatchResult(f"sceneIndex={scene_index} tags 非字符串数组")
        if isinstance(importance, bool) or not isinstance(importance, (int, float)):
            raise _InvalidBatchResult(f"sceneIndex={scene_index} importance 非数值")
        if not 0 <= float(importance) <= 1:
            raise _InvalidBatchResult(f"sceneIndex={scene_index} importance 越界")
        observations[scene_index] = {
            "description": description.strip(),
            "tags": tags,
            "importance": float(importance),
        }

    if set(observations) != expected:
        missing = sorted(expected - set(observations))
        raise _InvalidBatchResult(f"缺少 sceneIndex={missing}")
    summary = data.get("batchSummary", "")
    if not isinstance(summary, str):
        raise _InvalidBatchResult("batchSummary 非字符串")
    return {"summary": summary.strip(), "observations": observations}


def _classify_failure(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}".lower()
    if isinstance(exc, _InvalidBatchResult) or "json" in text:
        return "INVALID_RESULT"
    if "timeout" in text or "timed out" in text:
        return "TIMEOUT"
    if "429" in text or "rate limit" in text:
        return "RATE_LIMIT"
    if "401" in text or "403" in text or "auth" in text:
        return "AUTHENTICATION"
    if "503" in text or "504" in text or "service unavailable" in text:
        return "UPSTREAM_UNAVAILABLE"
    if "connect" in text:
        return "CONNECTION"
    return "UNKNOWN"


def _call_batch(batch_id: str, items: Sequence[dict], transcripts, meta, attempt: int) -> dict:
    started = time.monotonic()
    expected_indices = [item["sceneIndex"] for item in items]
    metric = {
        "batchId": batch_id,
        "sceneIndices": expected_indices,
        "imageCount": len(items),
        "attempt": attempt,
        "retry": attempt > 0,
        "detail": config.VLM_IMAGE_DETAIL,
        "timeoutSeconds": config.VLM_BATCH_TIMEOUT_SECONDS,
        "status": "FAILED",
        "failureType": None,
        "resultValid": False,
    }
    try:
        prompt = _build_batch_prompt(
            items,
            _related_transcripts(items, transcripts),
            meta,
        )
        reply = understand_frames(
            prompt,
            [item["framePath"] for item in items],
            detail=config.VLM_IMAGE_DETAIL,
            timeout=config.VLM_BATCH_TIMEOUT_SECONDS,
        )
        parsed = _parse_batch_reply(reply, expected_indices)
        metric["status"] = "SUCCESS"
        metric["resultValid"] = True
        return {"success": True, "parsed": parsed, "metrics": [metric]}
    except Exception as exc:
        metric["failureType"] = _classify_failure(exc)
        metric["error"] = str(exc)[:300]
        return {"success": False, "error": exc, "metrics": [metric]}
    finally:
        metric["elapsedMs"] = round((time.monotonic() - started) * 1000)
        logger.info(
            "VLM batch batchId=%s images=%d elapsedMs=%d status=%s "
            "failureType=%s retry=%s resultValid=%s",
            batch_id,
            len(items),
            metric["elapsedMs"],
            metric["status"],
            metric["failureType"],
            metric["retry"],
            metric["resultValid"],
        )


def _run_batch(batch_id: str, items: Sequence[dict], transcripts, meta) -> dict:
    primary = _call_batch(batch_id, items, transcripts, meta, attempt=0)
    if primary["success"]:
        return primary
    if primary["metrics"][0]["failureType"] == "AUTHENTICATION":
        return primary

    metrics = list(primary["metrics"])
    retries = max(0, config.VLM_BATCH_MAX_RETRIES)
    if retries == 0:
        return primary

    fallback_size = max(1, min(config.VLM_FALLBACK_IMAGES_PER_BATCH, len(items)))
    current_chunks = [
        list(items[offset : offset + fallback_size])
        for offset in range(0, len(items), fallback_size)
    ]
    for attempt in range(1, retries + 1):
        observations: dict[int, dict] = {}
        summaries: list[str] = []
        all_success = True
        for chunk_no, chunk in enumerate(current_chunks):
            child_id = f"{batch_id}.retry{attempt}.{chunk_no:02d}"
            child = _call_batch(child_id, chunk, transcripts, meta, attempt=attempt)
            metrics.extend(child["metrics"])
            if not child["success"]:
                all_success = False
                continue
            observations.update(child["parsed"]["observations"])
            if child["parsed"]["summary"]:
                summaries.append(child["parsed"]["summary"])
        if all_success:
            return {
                "success": True,
                "parsed": {
                    "summary": " ".join(summaries),
                    "observations": observations,
                },
                "metrics": metrics,
            }
        if observations:
            return {
                "success": False,
                "error": primary["error"],
                "parsed": {
                    "summary": " ".join(summaries),
                    "observations": observations,
                },
                "metrics": metrics,
            }
    return {
        "success": False,
        "error": primary["error"],
        "parsed": {"summary": "", "observations": {}},
        "metrics": metrics,
    }


def _simulate_scene_observation(scene_index: int, scenes, transcripts) -> dict:
    scene = scenes[scene_index]
    text = " ".join(
        transcript.text
        for transcript in transcripts
        if transcript.start < scene.end and transcript.end > scene.start
    ).strip()
    return {
        "description": text
        if text
        else f"场景 {scene.start:.1f}s~{scene.end:.1f}s（视觉分析缺失）",
        "tags": ["口播"] if text else ["未分析"],
        "importance": 0.9 if text else 0.3,
    }


def _merge_batch_results(scenes, transcripts, batch_results, missing_indices) -> dict:
    observations: dict[int, dict] = {}
    summaries: list[str] = []
    metrics: list[dict] = []
    failed_indices = set(missing_indices)
    for result in batch_results:
        metrics.extend(result["metrics"])
        parsed = result.get("parsed") or {}
        observations.update(parsed.get("observations", {}))
        if parsed.get("summary"):
            summaries.append(parsed["summary"])
        if result["success"]:
            continue
        expected_indices = {
            scene_index
            for metric in result["metrics"]
            if metric["attempt"] == 0
            for scene_index in metric["sceneIndices"]
        }
        failed_indices.update(expected_indices - set(parsed.get("observations", {})))

    for scene_index in range(len(scenes)):
        if scene_index not in observations:
            observations[scene_index] = _simulate_scene_observation(
                scene_index,
                scenes,
                transcripts,
            )
            failed_indices.add(scene_index)

    ordered = [observations[i] for i in range(len(scenes))]
    mode = "REAL" if not failed_indices else "MIXED"
    notes = ""
    if failed_indices:
        notes = f"VLM 局部降级 sceneIndex={sorted(failed_indices)}"
    return {
        "summary": " ".join(summaries).strip(),
        "sceneDescriptions": [item["description"] for item in ordered],
        "sceneTags": [item["tags"] for item in ordered],
        "sceneImportance": [item["importance"] for item in ordered],
        "highlights": [],
        "suggestions": [],
        "notes": notes,
        "simulated": bool(failed_indices),
        "provenance": {
            "mode": mode,
            "provider": "vlm",
            "model": config.VLM_MODEL,
            "batchConfig": {
                "maxImages": config.VLM_MAX_IMAGES_PER_BATCH,
                "concurrency": config.VLM_CONCURRENCY,
                "detail": config.VLM_IMAGE_DETAIL,
                "timeoutSeconds": config.VLM_BATCH_TIMEOUT_SECONDS,
                "maxRetries": config.VLM_BATCH_MAX_RETRIES,
                "fallbackImages": config.VLM_FALLBACK_IMAGES_PER_BATCH,
            },
            "failedSceneIndices": sorted(failed_indices),
            "batches": metrics,
        },
    }


def understand_video(scenes, frames, transcripts, meta) -> dict:
    """分批分析场景帧，并兼容旧 AnalysisReport 所需的数组字段。"""
    if config.SIMULATE_FORCED or not _HAS_OPENAI or not config.VLM_API_KEY or not frames:
        return _simulate_understanding(scenes, transcripts, meta, "模拟模式或缺少 VLM 配置")

    indexed_frames, missing_indices = _index_frames(scenes, frames)
    if not indexed_frames:
        return _simulate_understanding(scenes, transcripts, meta, "没有可映射的场景帧")

    batch_size = max(1, config.VLM_MAX_IMAGES_PER_BATCH)
    batches = [
        indexed_frames[offset : offset + batch_size]
        for offset in range(0, len(indexed_frames), batch_size)
    ]
    results: list[dict | None] = [None] * len(batches)
    with ThreadPoolExecutor(max_workers=max(1, config.VLM_CONCURRENCY)) as executor:
        futures = {
            executor.submit(
                _run_batch,
                f"batch_{batch_no:03d}",
                batch,
                transcripts,
                meta,
            ): batch_no
            for batch_no, batch in enumerate(batches)
        }
        for future in as_completed(futures):
            batch_no = futures[future]
            try:
                results[batch_no] = future.result()
            except Exception as exc:  # 防止单批执行器异常取消其他批次
                logger.exception("VLM 批次执行异常: batch_%03d", batch_no)
                results[batch_no] = {
                    "success": False,
                    "error": exc,
                    "metrics": [
                        {
                            "batchId": f"batch_{batch_no:03d}",
                            "sceneIndices": [
                                item["sceneIndex"] for item in batches[batch_no]
                            ],
                            "imageCount": len(batches[batch_no]),
                            "attempt": 0,
                            "retry": False,
                            "detail": config.VLM_IMAGE_DETAIL,
                            "timeoutSeconds": config.VLM_BATCH_TIMEOUT_SECONDS,
                            "elapsedMs": 0,
                            "status": "FAILED",
                            "failureType": _classify_failure(exc),
                            "resultValid": False,
                            "error": str(exc)[:300],
                        }
                    ],
                }
    return _merge_batch_results(
        scenes,
        transcripts,
        [result for result in results if result is not None],
        missing_indices,
    )


def _simulate_frames_reply(prompt: str, frame_paths) -> str:
    """模拟 VLM 帧图回复（占位）。"""
    return f"[模拟 VLM] 已分析 {len(frame_paths)} 张帧图。prompt 摘要: {prompt[:80]}..."


def _simulate_understanding(scenes, transcripts, meta, reason: str = "模拟理解") -> dict:
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
    suggestions = []
    if ranked:
        suggestions.append(
            {"type": "keep", "sceneIndex": ranked[0], "reason": "核心内容，建议保留", "params": {}}
        )
    if len(ranked) > 1:
        suggestions.append(
            {"type": "keep", "sceneIndex": ranked[1], "reason": "亮点片段，建议保留", "params": {}}
        )
        suggestions.append(
            {"type": "delete", "sceneIndex": ranked[-1], "reason": "重要性低，可考虑删除", "params": {}}
        )
    suggestions.append(
        {"type": "subtitle", "sceneIndex": None, "reason": "建议全片添加字幕提升可读性", "params": {}}
    )
    return {
        "summary": "这是一个口播类视频，围绕主题依次展开，中段为重点讲解部分。",
        "sceneDescriptions": scene_desc,
        "sceneTags": scene_tags,
        "sceneImportance": scene_importance,
        "highlights": highlights,
        "suggestions": suggestions,
        "notes": f"模拟理解（{reason}）",
        "simulated": True,
        "provenance": {"mode": "SIMULATED", "reason": reason},
    }
