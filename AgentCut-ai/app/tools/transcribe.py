"""FunASR 语音转写工具（app.tools.transcribe）。

默认 paraformer-zh（中文最优、精确时间戳），输出带秒级时间戳的文本段列表。
依赖缺失 / 模拟模式下返回与场景对齐的占位转写，保证数据流完整。
"""

import logging
import os
from threading import Lock
from typing import List, Optional, Sequence

from app import config
from app.schemas.analysis import TranscriptSegment
from app.schemas.plan import TimeRange
from app.tools.frame_extract import probe_video

logger = logging.getLogger(__name__)

# FunASR 模型懒加载（全局唯一，避免重复初始化）
_model = None
_model_lock = Lock()

# 模拟转写用示例句（中文口播风格）
_SAMPLE_SENTENCES = [
    "大家好，欢迎来到本期视频，今天我们要聊一个非常有意思的话题。",
    "首先我们来看第一部分，这里有几个关键点值得注意。",
    "接下来进入重点环节，这些细节决定了整个方案的走向。",
    "当然这里也有一个常见误区，很多人在这一步会犯错。",
    "最后做个总结，记住这几个要点，你就能轻松上手了。",
    "如果对你有帮助，记得点赞关注，我们下期再见。",
]


def _get_model():
    """懒加载 FunASR AutoModel（paraformer-zh + 前端 VAD + 标点）。"""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from funasr import AutoModel

                _model = AutoModel(
                    model="paraformer-zh",
                    vad_model="fsmn-vad",
                    punc_model="ct-punc",
                    disable_update=True,
                )
    return _model


def _parse_result(res: list) -> List[TranscriptSegment]:
    """解析 FunASR generate 返回：优先 sentence_info（毫秒级句子时间戳）。"""
    segs: List[TranscriptSegment] = []
    if not res or not isinstance(res[0], dict):
        return segs
    sentences = res[0].get("sentence_info") or []
    for i, sent in enumerate(sentences):
        start_ms = sent.get("start", 0)
        end_ms = sent.get("end", start_ms)
        text = sent.get("text", "")
        if not text:
            continue
        segs.append(
            TranscriptSegment(
                index=i,
                start=round(start_ms / 1000.0, 3),
                end=round(end_ms / 1000.0, 3),
                text=text,
            )
        )
    return segs


def _simulate_transcript(scenes: Sequence[TimeRange]) -> List[TranscriptSegment]:
    """模拟转写：每个场景生成一句占位口播文本（MVP 降级）。"""
    segs: List[TranscriptSegment] = []
    for i, sc in enumerate(scenes):
        segs.append(
            TranscriptSegment(
                index=i,
                start=round(sc.start, 3),
                end=round(sc.end, 3),
                text=_SAMPLE_SENTENCES[i % len(_SAMPLE_SENTENCES)],
            )
        )
    return segs


def transcribe(
    video_path: Optional[str],
    scenes: Optional[Sequence[TimeRange]] = None,
    lang: str = "zh",
) -> List[TranscriptSegment]:
    """转写视频语音，返回带时间戳的文本段列表。

    - scenes 提供时，模拟模式按其边界生成占位转写，保证与场景对齐；
    - 真实路径：FunASR AutoModel.generate 解析 sentence_info。
    """
    if not scenes:
        meta = probe_video(video_path)
        scenes = [TimeRange(start=0.0, end=meta["duration"])]

    # 模拟 / 文件缺失 / 依赖缺失 → 占位转写
    if config.SIMULATE or not video_path or not os.path.exists(video_path):
        logger.warning("transcribe 进入模拟模式（video_path=%s）", video_path)
        return _simulate_transcript(scenes)

    try:
        import funasr  # noqa: F401
    except Exception as exc:
        logger.warning("FunASR 未安装，转写进入模拟模式：%s", exc)
        return _simulate_transcript(scenes)

    try:
        model = _get_model()
        # batch_size_s 控制批处理时长；language 限定语言
        res = model.generate(input=video_path, batch_size_s=300, language=lang)
        segs = _parse_result(res)
        if not segs:  # 空结果兜底
            logger.warning("FunASR 未返回文本，转写进入模拟模式")
            return _simulate_transcript(scenes)
        logger.info("transcribe 完成，共 %d 段", len(segs))
        return segs
    except Exception as exc:
        logger.warning("transcribe 失败，降级为模拟转写：%s", exc)
        return _simulate_transcript(scenes)
