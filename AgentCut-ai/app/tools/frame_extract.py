"""PyAV 抽帧工具（app.tools.frame_extract）。

职责：
- probe_video                读取视频元数据（时长 / 分辨率 / fps / 是否含音轨），作为 ffprobe 的轻量替代
- extract_frames_at_times    在指定时间点抽帧（精确 seek）
- extract_frames_by_interval 按固定时间间隔抽帧（如 1fps 采样）
- extract_frames_by_scenes   按场景边界抽帧（默认每场景取中间 1 帧）

依赖：PyAV（import av）+ opencv-python（写 jpg）。两者缺失 / 文件不存在时
降级返回空列表 / 模拟元数据，保证服务在无本地环境时仍可端到端跑通。
"""

import logging
import os
from typing import List, Optional, Sequence

from app.schemas.plan import TimeRange

logger = logging.getLogger(__name__)

# 重型依赖可选：缺失时进入模拟模式
try:  # pragma: no cover - 依赖缺失时的降级路径
    import av
    import cv2

    _HAS_AV = True
except Exception as exc:  # pragma: no cover
    av = None
    cv2 = None
    _HAS_AV = False
    logger.warning("PyAV / opencv-python 未安装，抽帧工具进入模拟模式：%s", exc)


def probe_video(video_path: Optional[str]) -> dict:
    """探测视频元数据。

    文件不存在或 PyAV 缺失时返回模拟元数据（MVP 降级，默认 60s / 1920x1080 / 30fps）。
    """
    if _HAS_AV and video_path and os.path.exists(video_path):
        try:
            container = av.open(video_path)
            video = container.streams.video[0]
            if video.duration is not None and video.time_base is not None:
                duration = float(video.duration * video.time_base)
            else:
                duration = float(container.duration * av.time_base)
            fps = float(video.average_rate) if video.average_rate else 30.0
            meta = {
                "duration": round(duration, 3),
                "fps": round(fps, 3),
                "width": video.codec_context.width,
                "height": video.codec_context.height,
                "has_audio": bool(container.streams.audio),
            }
            container.close()
            return meta
        except Exception as exc:
            logger.warning("probe_video 失败，降级为模拟元数据：%s", exc)
    logger.info("probe_video 进入模拟模式（video_path=%s）", video_path)
    return {"duration": 60.0, "fps": 30.0, "width": 1920, "height": 1080, "has_audio": True}


def _grab_frame(container, stream, target_sec: float):
    """seek 到目标时间附近并解码出最接近 target_sec 的一帧。"""
    stream_tb = stream.time_base
    seek_offset = max(0, int((target_sec - 0.1) / stream_tb))  # 目标前 0.1s，保证能解到目标帧
    container.seek(seek_offset, stream=stream)
    best = None
    for frame in container.decode(video=0):
        t = frame.time
        if t is None:
            continue
        if best is None or abs(t - target_sec) < abs(best.time - target_sec):
            best = frame
        if t >= target_sec:
            break
    return best


def _save_frame(frame, path: str) -> None:
    """把 PyAV 帧写成 jpg（opencv 写出，bgr24 避免额外色彩转换依赖）。"""
    ndarray = frame.to_ndarray(format="bgr24")
    cv2.imwrite(path, ndarray)


def _frange(start: float, stop: float, step: float):
    """浮点等差数列（避免引入 numpy 依赖）。"""
    x = start
    while x < stop - 1e-6:
        yield x
        x += step


def extract_frames_at_times(
    video_path: str,
    times: Sequence[float],
    output_dir: str,
    prefix: str = "frame",
) -> List[str]:
    """在指定时间点抽帧，返回保存的图片路径列表。"""
    saved: List[str] = []
    if not _HAS_AV or not video_path or not os.path.exists(video_path):
        logger.warning("extract_frames_at_times 跳过（无视频文件或依赖缺失）：%s", video_path)
        return saved
    os.makedirs(output_dir, exist_ok=True)
    container = av.open(video_path)
    video = container.streams.video[0]
    try:
        for i, t in enumerate(times):
            frame = _grab_frame(container, video, float(t))
            if frame is None:
                continue
            path = os.path.join(output_dir, f"{prefix}_{i:04d}_{t:.3f}.jpg")
            _save_frame(frame, path)
            saved.append(path)
    finally:
        container.close()
    logger.info("extract_frames_at_times 共抽帧 %d 张", len(saved))
    return saved


def extract_frames_by_interval(
    video_path: str,
    output_dir: str,
    interval: float = 1.0,
    prefix: str = "frame",
) -> List[str]:
    """按固定时间间隔抽帧（如 interval=1.0 即 1fps 采样）。"""
    meta = probe_video(video_path)
    times = [round(t, 3) for t in _frange(0.0, meta["duration"], interval)]
    return extract_frames_at_times(video_path, times, output_dir, prefix)


def extract_frames_by_scenes(
    video_path: str,
    scenes: Sequence[TimeRange],
    output_dir: str,
    prefix: str = "scene",
    frames_per_scene: int = 1,
) -> List[str]:
    """按场景边界抽帧（默认每场景取中间 1 帧）。"""
    times: List[float] = []
    for sc in scenes:
        if frames_per_scene <= 1:
            times.append(sc.start + (sc.end - sc.start) / 2.0)
        else:
            for k in range(frames_per_scene):
                times.append(sc.start + (sc.end - sc.start) * (k + 0.5) / frames_per_scene)
    return extract_frames_at_times(video_path, times, output_dir, prefix)
