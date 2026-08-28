"""PySceneDetect 场景切分工具（app.tools.scene_detect）。

基于 ContentDetector（内容差异）检测镜头边界，返回场景时间区间列表（TimeRange）。
依赖缺失 / 文件不存在时返回模拟场景（配合模拟模式端到端跑通）。
"""

import logging
import os
from typing import List, Optional

from app.schemas.plan import TimeRange
from app.tools.frame_extract import probe_video

logger = logging.getLogger(__name__)

# 重型依赖可选：缺失时进入模拟模式
try:  # pragma: no cover - 依赖缺失时的降级路径
    from scenedetect import SceneManager, open_video
    from scenedetect.detectors import ContentDetector

    _HAS_SCENEDETECT = True
except Exception as exc:  # pragma: no cover
    SceneManager = None
    open_video = None
    ContentDetector = None
    _HAS_SCENEDETECT = False
    logger.warning("PySceneDetect 未安装，场景检测进入模拟模式：%s", exc)


def _simulate_scenes(duration: float, n: int = 6) -> List[TimeRange]:
    """模拟场景：把时长均分为 n 段（MVP 降级数据）。"""
    step = duration / n
    return [
        TimeRange(start=round(i * step, 3), end=round((i + 1) * step, 3))
        for i in range(n)
    ]


def _decide_max_scenes(duration: float) -> int:
    """根据视频时长决定场景数上限（每 8 秒约 1 帧，最少 8，封顶 24）。

    帧数随视频长度合理变化；封顶 24 是为了控制一次性传给 VLM 的帧数，
    避免请求体过大导致处理缓慢/超时（实测 36 帧会显著变慢）。
    """
    return max(8, min(24, int(duration / 8)))


def _to_seconds(tc) -> float:
    """把 scenedetect 的 FrameTimecode 兼容转成秒。"""
    get = getattr(tc, "get_seconds", None)
    return float(get()) if get else float(tc)


def detect_scenes(
    video_path: Optional[str],
    threshold: float = 27.0,
    min_scene_len: float = 0.4,
) -> List[TimeRange]:
    """检测场景边界，返回按时间升序的场景区间列表。"""
    meta = probe_video(video_path)
    duration = meta["duration"]

    if not _HAS_SCENEDETECT or not video_path or not os.path.exists(video_path):
        logger.warning("detect_scenes 进入模拟模式（video_path=%s）", video_path)
        return _simulate_scenes(duration)

    try:
        video = open_video(video_path)
        sm = SceneManager()
        sm.add_detector(ContentDetector(threshold=threshold))
        # 缩小检测分辨率以提速（scenedetect >= 0.6 支持）
        try:
            sm.auto_downscale = True
        except Exception:
            pass
        sm.detect_scenes(video)
        scene_list = sm.get_scene_list()
        # scenedetect 0.7 的 VideoStreamCv2 无 close()，有则调用，无则交给 gc 释放
        close = getattr(video, "close", None)
        if close:
            close()

        if not scene_list:  # 未检出任何边界 → 整片视为一个场景
            return [TimeRange(start=0.0, end=duration)]

        scenes: List[TimeRange] = []
        for start_tc, end_tc in scene_list:
            s = _to_seconds(start_tc)
            e = _to_seconds(end_tc)
            if e - s >= min_scene_len:
                scenes.append(TimeRange(start=round(s, 3), end=round(e, 3)))
        if not scenes:  # 全部过短则整片视为一个场景
            return [TimeRange(start=0.0, end=duration)]
        # 场景过多时按动态预算均匀采样（预算随视频时长变化，避免固定帧数对长视频过稀）
        max_scenes = _decide_max_scenes(duration)
        if len(scenes) > max_scenes:
            step = len(scenes) / max_scenes
            scenes = [scenes[int(i * step)] for i in range(max_scenes)]
        return scenes
    except Exception as exc:
        logger.warning("detect_scenes 失败，降级为模拟场景：%s", exc)
        return _simulate_scenes(duration)
