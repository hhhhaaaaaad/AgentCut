"""语音转写工具（app.tools.transcribe）。

真实路径优先级：SiliconFlow ASR API（Qwen3-ASR，复用 VLM key，带真实时间戳）
→ 本地 FunASR（paraformer-zh，需 torch）→ 模拟占位。
"""

import logging
import math
import os
import re
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

# ASR API 分片参数：单片段时长上限（秒）与片段重叠（秒，避免切词）
_MAX_SEGMENT_SECONDS = 60
_SEGMENT_OVERLAP = 1.0

# ASR 输出中的音乐标记（部分 ASR 模型对背景音乐片段输出这些符号，需清理）
_MUSIC_MARKS = ("🎼", "🎵", "🎶")


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


def _transcribe_via_api(video_path: str, scenes: Sequence[TimeRange]) -> List[TranscriptSegment]:
    """用 SiliconFlow ASR + VAD 预分割 + 合并转写，返回带真实时间戳的文本段。

    流程：FFmpeg 抽音频 → VAD 检测语音段 → 合并相邻段（每块 ≤ 30s）→ 逐块调 ASR → 组装带时间戳段。
    VAD 保证精确时间戳 + 跳过静音；合并避免调用过多 & 长音频 Connection error。
    """
    import shutil
    import subprocess
    import tempfile

    client = config.get_openai_client()
    if client is None:
        raise RuntimeError("SiliconFlow 客户端不可用")

    tmpdir = tempfile.mkdtemp(prefix="agentcut_asr_")
    try:
        # 1. FFmpeg 抽音频（16kHz 16bit 单声道 wav）
        audio_path = os.path.join(tmpdir, "full.wav")
        subprocess.run(
            ["ffmpeg", "-y", "-i", video_path, "-vn", "-ac", "1", "-ar", "16000",
             "-acodec", "pcm_s16le", audio_path],
            check=True, capture_output=True,
        )

        # 2. VAD 检测语音段；无语音/失败则回退 30s 粗切
        speech = _detect_speech_segments(audio_path)
        if not speech:
            duration = _audio_duration(audio_path) or 30.0
            speech = [(s, min(s + 30.0, duration)) for s in range(0, int(duration) + 1, 30)]

        # 3. 合并相邻段（每块 ≤ 30s），逐块转写
        results: List[TranscriptSegment] = []
        for idx, (start, end) in enumerate(_merge_speech_segments(speech, max_chunk=30.0, gap=1.0)):
            seg_path = os.path.join(tmpdir, f"seg_{idx}.wav")
            subprocess.run(
                ["ffmpeg", "-y", "-ss", str(start), "-t", str(end - start), "-i", audio_path,
                 "-c", "copy", seg_path],
                check=True, capture_output=True,
            )
            try:
                text = _transcribe_audio_file(client, seg_path)
                if text:
                    results.append(TranscriptSegment(
                        index=idx, start=round(start, 3), end=round(end, 3), text=text,
                    ))
            except Exception as exc:
                logger.warning("音频块 %.1fs~%.1fs 转写失败：%s", start, end, exc)
        return results
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _merge_speech_segments(segments: List[tuple], max_chunk: float = 30.0, gap: float = 1.0) -> List[tuple]:
    """合并相邻语音段（段间距 ≤ gap），再把超长段切成 ≤ max_chunk 块。"""
    if not segments:
        return []
    # 1. 合并相邻段
    merged = []
    cur_start, cur_end = segments[0]
    for start, end in segments[1:]:
        if start - cur_end <= gap:
            cur_end = max(cur_end, end)
        else:
            merged.append((cur_start, cur_end))
            cur_start, cur_end = start, end
    merged.append((cur_start, cur_end))
    # 2. 超长段切成 max_chunk 块（避免整段长音频触发 Connection error）
    chunks = []
    for start, end in merged:
        while end - start > max_chunk + 1e-6:
            chunks.append((start, start + max_chunk))
            start += max_chunk
        if end > start:
            chunks.append((start, end))
    return chunks


def _detect_speech_segments(audio_path: str, frame_ms: int = 30, min_segment: float = 0.3) -> List[tuple]:
    """用 webrtcvad 检测语音段，返回 [(start, end), ...]（秒）。"""
    import wave
    import webrtcvad

    try:
        vad = webrtcvad.Vad(2)  # 敏感度 0~3，2 为中等
    except Exception as exc:
        logger.warning("webrtcvad 初始化失败：%s", exc)
        return []

    with wave.open(audio_path, "rb") as wf:
        sample_rate = wf.getframerate()
        n_channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        # webrtcvad 仅支持 16kHz 16bit 单声道
        if sample_rate != 16000 or n_channels != 1 or sample_width != 2:
            logger.warning("音频格式不满足 VAD 要求：%dHz/%dch/%dB", sample_rate, n_channels, sample_width)
            return []
        frame_size = int(sample_rate * frame_ms / 1000)
        speech_flags = []
        raw = wf.readframes(frame_size)
        while len(raw) == frame_size * sample_width:
            speech_flags.append(vad.is_speech(raw, sample_rate))
            raw = wf.readframes(frame_size)

    # 合并连续语音帧成段
    segments = []
    seg_start = None
    frame_dur = frame_ms / 1000.0
    for i, is_speech in enumerate(speech_flags):
        t = i * frame_dur
        if is_speech and seg_start is None:
            seg_start = t
        elif not is_speech and seg_start is not None:
            if t - seg_start >= min_segment:
                segments.append((seg_start, t))
            seg_start = None
    if seg_start is not None:
        end = len(speech_flags) * frame_dur
        if end - seg_start >= min_segment:
            segments.append((seg_start, end))
    return segments


def _audio_duration(audio_path: str) -> float:
    """用 ffprobe 探测音频时长（秒）；失败返回 0。"""
    import subprocess

    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
        capture_output=True, text=True,
    )
    try:
        return float(out.stdout.strip())
    except Exception:
        return 0.0


def _transcribe_audio_file(client, audio_path: str) -> str:
    """调 ASR API 转写单个音频文件，返回清理后的纯文本。"""
    with open(audio_path, "rb") as fh:
        resp = client.audio.transcriptions.create(model=config.ASR_MODEL, file=fh)
    return _clean_text(resp.text or "")


def _clean_text(text: str) -> str:
    """清理 ASR 转写文本：去除音乐标记，压缩多余空白。"""
    if not text:
        return text
    for mark in _MUSIC_MARKS:
        text = text.replace(mark, "")
    return re.sub(r"\s+", " ", text).strip()


def _transcribe_in_segments(client, audio_path: str, duration: float, tmpdir: str) -> str:
    """长音频分片转写：切成 60s 片段（含 1s 重叠），逐片调 API，合并去重。"""
    import subprocess

    parts = []
    start = 0.0
    seg_len = _MAX_SEGMENT_SECONDS + _SEGMENT_OVERLAP
    while start < duration:
        seg_path = os.path.join(tmpdir, f"seg_{int(start)}.mp3")
        subprocess.run(
            ["ffmpeg", "-y", "-ss", str(start), "-t", str(seg_len), "-i", audio_path,
             "-c", "copy", seg_path],
            check=True, capture_output=True,
        )
        try:
            text = _transcribe_audio_file(client, seg_path)
            if text:
                parts.append(text)
        except Exception as exc:
            logger.warning("分片 %.1fs~%.1fs 转写失败：%s", start, start + seg_len, exc)
        start += _MAX_SEGMENT_SECONDS
    return _merge_parts(parts)


def _merge_parts(parts: Sequence[str]) -> str:
    """合并分片文本，去重相邻片段的尾部/头部重叠字符。"""
    merged = ""
    for part in parts:
        if not part:
            continue
        if not merged:
            merged = part
            continue
        cut = 0
        max_k = min(len(merged), len(part), 10)
        for k in range(max_k, 0, -1):
            if merged[-k:] == part[:k]:
                cut = k
                break
        merged += part[cut:]
    return merged


def _distribute_text(text: str, scenes: Sequence[TimeRange]) -> List[TranscriptSegment]:
    """把整段转写文本按句子切分，近似分配到各场景区间（API 无时间戳，用场景边界近似）。"""
    sentences = [s.strip() for s in re.split(r"[。！？!?；;]", text) if s.strip()]
    if not sentences:
        return []
    n = len(scenes)
    per = max(1, math.ceil(len(sentences) / n))
    segs: List[TranscriptSegment] = []
    for i, sc in enumerate(scenes):
        start_idx = i * per
        end_idx = min(start_idx + per, len(sentences))
        if start_idx >= len(sentences):
            break
        chunk = "".join(sentences[start_idx:end_idx])
        if not chunk:
            continue
        segs.append(
            TranscriptSegment(
                index=i,
                start=round(sc.start, 3),
                end=round(sc.end, 3),
                text=chunk,
            )
        )
    return segs


def transcribe(
    video_path: Optional[str],
    scenes: Optional[Sequence[TimeRange]] = None,
    lang: str = "zh",
) -> List[TranscriptSegment]:
    """转写视频语音，返回带时间戳的文本段列表。

    真实路径优先级：SiliconFlow ASR API（需 VLM_API_KEY，无需本地 torch）
    → 本地 FunASR（需 torch）→ 模拟占位。
    """
    if not scenes:
        meta = probe_video(video_path)
        scenes = [TimeRange(start=0.0, end=meta["duration"])]

    # 文件缺失 → 占位转写
    if not video_path or not os.path.exists(video_path):
        logger.warning("transcribe 文件缺失，进入模拟（video_path=%s）", video_path)
        return _simulate_transcript(scenes)

    # ① 优先：SiliconFlow ASR API（复用 VLM key，无需本地 torch）
    if not config.SIMULATE_FORCED and config.VLM_API_KEY:
        try:
            segs = _transcribe_via_api(video_path, scenes)
            if segs:
                logger.info("SiliconFlow ASR 完成，共 %d 段", len(segs))
                return segs
        except Exception as exc:
            logger.warning("SiliconFlow ASR 失败，降级本地/模拟：%s", exc)

    # ② 本地 FunASR（需 torch）→ ③ 模拟降级
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
