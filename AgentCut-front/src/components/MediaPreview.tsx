import { useEffect, useRef, useState } from 'react';
import { Landscape } from './StudioUI';
import { formatTime } from '../lib/format';

interface Props {
  src?: string;
  demo?: boolean;
  variant?: 'source' | 'output';
  fileName?: string;
  segmentId?: string;
  duration: number;
  currentTime: number;
  onTimeChange: (time: number) => void;
  ratio?: string;
  subtitle?: string;
}

export function MediaPreview({ src, demo = false, variant = 'source', fileName, segmentId, duration, currentTime, onTimeChange, ratio, subtitle }: Props) {
  const video = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const [loadedDuration, setLoadedDuration] = useState(0);
  const [speed, setSpeed] = useState(1);
  const total = duration || loadedDuration;
  const hasMedia = !!src && !unavailable && !demo;
  const canPlay = hasMedia || demo;
  const portrait = variant === 'output';
  useEffect(() => { setUnavailable(false); setPlaying(false); setLoadedDuration(0); }, [src]);
  useEffect(() => {
    if (video.current && Math.abs(video.current.currentTime - currentTime) > .45) video.current.currentTime = currentTime;
  }, [currentTime]);
  useEffect(() => { if (video.current) video.current.playbackRate = speed; }, [speed]);
  useEffect(() => {
    if (!demo || !playing) return;
    const timer = setTimeout(() => {
      if (currentTime >= total) { setPlaying(false); onTimeChange(0); }
      else onTimeChange(Math.min(total, currentTime + .2 * speed));
    }, 200);
    return () => clearTimeout(timer);
  }, [demo, playing, currentTime, total, speed, onTimeChange]);

  const toggle = async () => {
    if (demo) { setPlaying(!playing); return; }
    if (!hasMedia || !video.current) return;
    if (video.current.paused) {
      try { await video.current.play(); } catch { setPlaying(false); }
    } else video.current.pause();
  };

  return <section className={`media-preview ${portrait ? 'output-preview' : 'source-preview'}`} aria-label={portrait ? '成片预览' : '源视频预览'}>
    {portrait && <div className="output-preview-header"><h2>成片预览</h2><span className="mono">{ratio || '—'} · 输出视频</span></div>}
    <div className="preview-body">
      {portrait && <div className="output-preview-caption"><small>OUTPUT VIDEO</small><strong>{fileName || '等待生成成片'}</strong><span>{demo ? '画面示意' : hasMedia ? '成片预览' : '手动应用方案后生成'}</span></div>}
      <div className="video-stage">
        {demo ? <Landscape portrait={portrait}/> : hasMedia ? <video ref={video} src={src} preload="metadata" playsInline onLoadedMetadata={() => setLoadedDuration(video.current?.duration || 0)} onTimeUpdate={() => onTimeChange(video.current?.currentTime || 0)} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)} onError={() => { setUnavailable(true); setPlaying(false); }}/> : <div className="media-unavailable"><span aria-hidden>▷</span><strong>{portrait ? '成片将在这里预览' : '源视频暂不可预览'}</strong><p>{portrait ? '确认方案后，点击“应用方案”生成成片。' : '上传视频后可预览；本地路径无法直接在浏览器播放。'}</p></div>}
        {!portrait && <div className="video-stage-top"><strong>{fileName || '源视频'} · 原视频</strong>{demo && <span>画面示意</span>}</div>}
        {canPlay && !playing && <button className="big-play" onClick={() => void toggle()} aria-label="播放视频"><span aria-hidden>▶</span></button>}
        {canPlay && playing && <button className="video-pause-overlay" aria-label="暂停视频" onClick={() => void toggle()}/>}
        {!portrait && <div className="video-stage-bottom"><span className="mono">{segmentId ? `当前片段  ${segmentId}` : '源视频预览'}</span><span className="mono">{formatTime(currentTime, true)} / {formatTime(total)}</span></div>}
        {portrait && demo && subtitle && <div className="preview-subtitle">{subtitle}</div>}
      </div>
      {portrait && <div className="output-preview-note"><strong>输出预览</strong><span>{demo ? '设计示例画面' : hasMedia ? '已完成渲染' : '等待生成'}</span></div>}
    </div>
    <div className="preview-controls"><button aria-label={playing ? '暂停' : '播放'} disabled={!canPlay} onClick={() => void toggle()}>{playing ? 'Ⅱ' : '▶'}</button><span className="mono">{formatTime(currentTime, !portrait)}{portrait && ` / ${formatTime(total)}`}</span><input type="range" aria-label="视频播放进度" min={0} max={total || 1} step={.1} value={Math.min(total || 1, currentTime)} disabled={!canPlay} onChange={(event) => onTimeChange(Number(event.target.value))}/>{!portrait && <><button className="mono playback-speed" aria-label={`播放速度 ${speed} 倍`} disabled={!canPlay} onClick={() => setSpeed(speed === 1 ? 1.5 : speed === 1.5 ? 2 : 1)}>{speed.toFixed(1)}×</button><span className="mono preview-ratio">{ratio}</span></>}</div>
  </section>;
}
