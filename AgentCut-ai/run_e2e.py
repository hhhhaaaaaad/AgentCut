"""AgentCut 端到端全链路测试脚本（真实模式）。

流程：AnalysisAgent 分析视频 → PlanAgent 生成剪辑脚本（导演 + QA + 校验闸）
     → 保存 analysis/plan/quality 中间产物 → FFmpeg 渲染成片 → 输出量化指标。

用法：python run_e2e.py [video_path]
产物目录：E:\\java\\AgentCut\\work\\e2e_output\\<视频名>\\
环境开关：AGENTCUT_E2E_SKIP_ASR=1 跳过真实 ASR（规避限流）
"""

import json
import logging
import os
import subprocess
import sys
import time
from types import SimpleNamespace

from app import config
from app.agents.analysis_agent import AnalysisAgent
from app.agents.plan_agent import PlanAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("e2e")

DEFAULT_VIDEO = r"E:\java\AgentCut\huozhe4min10s.mp4"
OUT_BASE = r"E:\java\AgentCut\work\e2e_output"


# ---------------------------------------------------------------------------
# FFmpeg 渲染（镜像 Java RenderPlanService 的 Plan→FFmpeg 映射）
# ---------------------------------------------------------------------------


def _run_ffmpeg(argv, step=""):
    logger.info("[render] %s: %s", step or "ffmpeg", " ".join(argv))
    proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败(exit={proc.returncode}): {proc.stderr[-500:]}")
    return proc


def _build_drawtext(sub, style, font):
    text = sub.text.replace("\\", "\\\\").replace("'", "\\'")
    dt = "drawtext="
    if font and os.path.exists(font):
        f = font.replace("\\", "/").replace(":", "\\:")
        dt += f"fontfile='{f}':"
    dt += f"text='{text}'"
    if style is not None:
        if style.fontSize:
            dt += f":fontsize={style.fontSize}"
        if style.color:
            dt += f":fontcolor={style.color}"
        if style.position == "bottom":
            dt += ":x=(main_w-text_w)/2:y=main_h-text_h-40"
    dt += f":enable='between(t,{sub.start},{sub.end})'"
    return dt


def _build_segment_cmd(inp, seg, out, tw, th, tfps, style, font):
    cmd = ["ffmpeg", "-y", "-ss", str(seg.sourceRange.start),
           "-t", str(seg.sourceRange.end - seg.sourceRange.start), "-i", inp]
    vf, af, subtitles = [], [], []
    for op in seg.operations:
        t = op.type
        if t == "speed":
            vf.append(f"setpts=PTS/{op.rate}")
            af.append(f"atempo={op.rate}")
        elif t == "crop":
            vf.append(f"crop={op.width}:{op.height}:{op.x}:{op.y}")
        elif t == "subtitle":
            subtitles.append(_build_drawtext(op, style, font))
        elif t == "volume":
            af.append(f"volume={op.volume}")
        elif t == "mute":
            af.append("volume=0")
    vf.append(f"scale={int(round(tw))}:{int(round(th))}")
    vf.append(f"fps={int(round(tfps))}")
    vf.extend(subtitles)
    af.append("aresample=44100")
    if vf:
        cmd += ["-vf", ",".join(vf)]
    if af:
        cmd += ["-af", ",".join(af)]
    cmd += ["-c:v", "libx264", "-c:a", "aac", "-ar", "44100", out]
    return cmd


def render_plan(plan, out_dir, font=None):
    """把 Plan 渲染为成片，返回 (output_path, render_metrics)。"""
    source = plan.source
    out_cfg = plan.global_.output
    inp = source.url
    if inp.startswith("file://"):
        inp = inp[len("file://"):]
    tw = out_cfg.width if out_cfg.width > 0 else source.width
    th = out_cfg.height if out_cfg.height > 0 else source.height
    tfps = out_cfg.fps if out_cfg.fps > 0 else source.fps
    style = plan.global_.subtitleStyle

    kept = [s for s in plan.timeline if s.keep]
    seg_files = []
    for i, seg in enumerate(kept):
        seg_file = os.path.join(out_dir, f"seg_{i}.mp4")
        seg_files.append(seg_file)
        _run_ffmpeg(_build_segment_cmd(inp, seg, seg_file, tw, th, tfps, style, font), f"seg_{i}")

    concat_list = os.path.join(out_dir, "concat_list.txt")
    with open(concat_list, "w", encoding="utf-8") as fh:
        for sf in seg_files:
            fh.write(f"file '{os.path.basename(sf)}'\n")
    concat_file = os.path.join(out_dir, "concat.mp4")
    _run_ffmpeg(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", concat_file], "concat")

    output_path = os.path.join(out_dir, "output.mp4")
    _run_ffmpeg(["ffmpeg", "-y", "-i", concat_file, "-c", "copy", output_path], "final")

    dur = _probe_duration(output_path)
    size = os.path.getsize(output_path)
    return output_path, {
        "output_duration": round(dur, 1),
        "output_size_mb": round(size / 1024 / 1024, 1),
        "output_resolution": f"{int(round(tw))}x{int(round(th))}",
        "output_path": output_path,
    }


def _probe_duration(path):
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        return float(out.stdout.strip())
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def main():
    video = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_VIDEO
    name = os.path.splitext(os.path.basename(video))[0]
    out_dir = os.path.join(OUT_BASE, name)
    os.makedirs(out_dir, exist_ok=True)
    metrics = {"video": video}
    t0 = time.time()

    logger.info("=== 开始端到端，模式: real=%s simulate=%s ===",
                not config.SIMULATE, config.SIMULATE)

    # 可选：跳过真实 ASR（规避 SiliconFlow 限流），用占位转写，保留 VLM/LLM 真实
    if os.getenv("AGENTCUT_E2E_SKIP_ASR") == "1":
        import app.tools.transcribe as _tr
        from app.schemas.plan import TimeRange as _TR

        def _fast_transcribe(video_path, scenes=None, lang="zh"):
            if not scenes:
                from app.tools.frame_extract import probe_video
                meta = probe_video(video_path)
                scenes = [_TR(start=0.0, end=meta["duration"])]
            return _tr._simulate_transcript(scenes)

        _tr.transcribe = _fast_transcribe
        logger.warning("ASR 已降级为占位转写（AGENTCUT_E2E_SKIP_ASR=1）")

    try:
        # ① 分析
        asset_id = "asset_" + name
        t1 = time.time()
        agent = AnalysisAgent(work_dir=os.path.join(out_dir, "analysis"))
        report = agent.run(video, asset_id)
        metrics["analysis_seconds"] = round(time.time() - t1, 1)
        metrics["source_duration"] = round(report.duration, 1)
        metrics["source_size_mb"] = round(os.path.getsize(video) / 1024 / 1024, 1)
        metrics["source_resolution"] = f"{report.width}x{report.height}"
        metrics["source_fps"] = report.fps
        metrics["simulated"] = report.simulated
        metrics["scene_count"] = len(report.scenes)
        metrics["transcript_segment_count"] = len(report.transcripts)
        metrics["chapter_count"] = len(report.chapters)
        metrics["narration_wpm"] = report.narrationWordsPerMinute
        if report.narration:
            metrics["key_sentence_count"] = len(report.narration.keySentences)
            metrics["argument_count"] = len(report.narration.arguments)
            metrics["redundant_range_count"] = len(report.narration.redundancy)
        metrics["silence_range_count"] = len(report.silenceRanges)

        # ② 方案（导演 + QA + 校验闸）；自动识别竖屏/横屏
        aspect = "9:16" if report.height > report.width else "16:9"
        target = SimpleNamespace(aspectRatio=aspect, maxDuration=None, addSubtitle=False, style="")
        t2 = time.time()
        plan_agent = PlanAgent(project_id=asset_id)
        plan = plan_agent.run(report, target, asset_id)
        metrics["plan_seconds"] = round(time.time() - t2, 1)
        kept = [s for s in plan.timeline if s.keep]
        metrics["total_segments"] = len(plan.timeline)
        metrics["kept_segments"] = len(kept)
        metrics["deleted_segments"] = len(plan.timeline) - len(kept)
        metrics["aspect_ratio"] = aspect
        if plan_agent.last_quality is not None:
            metrics["qa_score"] = round(plan_agent.last_quality.overallScore, 3)
            metrics["qa_passed"] = plan_agent.last_quality.passed
            metrics["qa_issue_count"] = len(plan_agent.last_quality.issues)

        # ③ 保存中间产物
        with open(os.path.join(out_dir, "analysis.json"), "w", encoding="utf-8") as fh:
            fh.write(report.model_dump_json(indent=2))
        with open(os.path.join(out_dir, "plan.json"), "w", encoding="utf-8") as fh:
            fh.write(plan.to_contract_json())
        if plan_agent.last_quality is not None:
            with open(os.path.join(out_dir, "quality.json"), "w", encoding="utf-8") as fh:
                fh.write(plan_agent.last_quality.model_dump_json(indent=2))

        # ④ 渲染成片
        t3 = time.time()
        font = r"C:\Windows\Fonts\msyh.ttc"
        output_path, render_metrics = render_plan(plan, out_dir, font)
        metrics["render_seconds"] = round(time.time() - t3, 1)
        metrics.update(render_metrics)

    except Exception as exc:
        logger.exception("端到端失败")
        metrics["error"] = str(exc)

    metrics["total_seconds"] = round(time.time() - t0, 1)
    metrics_path = os.path.join(out_dir, "metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as fh:
        json.dump(metrics, fh, ensure_ascii=False, indent=2)

    logger.info("=== 完成，指标：%s", json.dumps(metrics, ensure_ascii=False))
    print("=== E2E_METRICS ===")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print("=== E2E_DONE ===")


if __name__ == "__main__":
    main()
