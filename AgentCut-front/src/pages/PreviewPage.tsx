import { useEffect, useState } from 'react';
import { Alert, App, Button } from 'antd';
import { applyPlan, getSavedPlan, renderDownloadUrl } from '../api';
import { MediaPreview } from '../components/MediaPreview';
import { Banner, EmptyState, PageHeading, Panel, StatusPill } from '../components/StudioUI';
import { aspectRatio, formatSize, formatTime, mediaUrl } from '../lib/format';
import { isRenderedPlanCurrent, outputDuration, savedPlanVersion, validatePlan } from '../lib/plan';
import { useProjectStore } from '../stores/projectStore';
import type { PageKey } from '../types/nav';

export default function PreviewPage({ onNavigate }: { onNavigate: (page: PageKey) => void }) {
  const { message } = App.useApp();
  const { project, plan, planVersions, planDirty, renderResult: result, renderedPlanVersion, renderedPlan, demo, setRenderResult, setPlan, setPlanVersions } = useProjectStore();
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [time, setTime] = useState(demo ? 21 : 0);
  const currentResult = !!result && renderedPlanVersion === savedPlanVersion(plan, planVersions) && isRenderedPlanCurrent(plan, renderedPlan, planDirty);
  const url = result?.taskId ? renderDownloadUrl(result.taskId) : mediaUrl(result?.outputPath);
  const outputPlan = result ? renderedPlan || plan : plan;

  useEffect(() => {
    if (!project || plan || demo) return;
    let cancelled = false;
    getSavedPlan(project.projectId).then(({ plan: value, versions }) => {
      if (cancelled) return;
      const issue = validatePlan(value);
      if (issue) setError(issue); else { setPlan(value); setPlanVersions(versions); }
    }).catch((err) => { if (!cancelled) setError(`加载方案失败：${err instanceof Error ? err.message : String(err)}`); });
    return () => { cancelled = true; };
  }, [project?.projectId, plan, demo, setPlan]);

  const handleApply = async () => {
    if (!project || !plan || planDirty || applying) return;
    const issue = validatePlan(plan);
    if (issue) { setError(issue); return; }
    if (demo) { message.info('界面示例不会发起渲染；请使用真实项目应用方案。'); return; }
    setApplying(true); setError(null);
    try {
      const output = await applyPlan(project.projectId);
      if (useProjectStore.getState().project?.projectId !== project.projectId) return;
      setRenderResult(output, plan); setTime(0);
      message.success('方案已应用，成片生成完成');
    } catch (err) { setError(`生成成片失败：${err instanceof Error ? err.message : String(err)}`); }
    finally { setApplying(false); }
  };
  const handleDownload = () => {
    if (demo) { message.info('这是设计示例，没有可下载的视频文件。'); return; }
    if (url) window.open(url, '_blank', 'noopener,noreferrer');
    else message.error('成片下载链接不可用，请重新应用方案。');
  };
  const copyPath = async () => {
    if (!result) return;
    try { await navigator.clipboard.writeText(result.outputPath); message.success('路径已复制'); }
    catch { message.error('复制失败，请选择路径文本手动复制'); }
  };

  return <>
    <Banner tone={currentResult ? 'success' : planDirty ? 'warning' : 'info'} title={currentResult ? '成片已生成，可以下载' : planDirty ? '请先保存方案修改，再生成成片' : result ? '当前方案已有更新，可以重新生成成片' : applying ? '正在应用方案，生成成片' : '确认剪辑方案，生成你的视频'} description={currentResult ? `剪辑方案 v${renderedPlanVersion} 已应用。下载前可核对时长、规格和保存路径。` : '应用方案会开始生成成片，请先确认片段、字幕和输出规格。'} trailing="步骤 4 / 4"/>
    <PageHeading title="预览导出" description="检查输出结果，确认后下载生成的视频" actions={<><Button onClick={() => onNavigate('edit')}>返回编辑</Button>{currentResult ? <Button type="primary" onClick={handleDownload}>下载成片</Button> : <Button type="primary" disabled={!plan || planDirty || !!(plan && validatePlan(plan))} loading={applying} onClick={() => void handleApply()}>{result ? '应用新版方案' : '应用方案，生成成片'}</Button>}</>}/>
    {error && <Alert className="page-error" type="error" showIcon message={error}/>}
    {!project || !plan ? <EmptyState title="还没有可导出的方案" description="先完成视频分析并保存剪辑方案，再生成成片。" action="去方案编辑" onAction={() => onNavigate('edit')}/> : <div className="export-layout">
      <MediaPreview variant="output" src={demo ? undefined : url} demo={demo && !!result} fileName={`AgentCut · ${project.title}`} duration={result?.duration || outputDuration(plan.timeline)} currentTime={time} onTimeChange={setTime} ratio={aspectRatio(outputPlan!.global.output.width, outputPlan!.global.output.height)} subtitle={outputPlan!.timeline.flatMap((segment) => segment.operations || []).find((operation) => operation.type === 'subtitle')?.text}/>
      <Panel title="成片结果" extra={<StatusPill status={result ? 'APPLIED' : applying ? 'RUNNING' : 'PENDING'}/>} className="export-result-panel"><div className="export-result-content">
        <div className="output-metrics"><div><small>成片时长</small><strong className="mono">{result ? formatTime(result.duration) : '—'}</strong></div><div><small>文件大小</small><strong className="mono">{result ? formatSize(result.size) : '—'}</strong></div></div>
        <section className="output-plan-info"><h3>使用的剪辑方案</h3><dl><div><dt>方案版本</dt><dd className="mono">v{result ? renderedPlanVersion : savedPlanVersion(plan, planVersions)}</dd></div><div><dt>片段</dt><dd>{outputPlan!.timeline.length} 段 / 保留 {outputPlan!.timeline.filter((segment) => segment.keep).length} 段</dd></div><div><dt>输出尺寸</dt><dd className="mono">{outputPlan!.global.output.width} × {outputPlan!.global.output.height}</dd></div></dl>{result && !currentResult && <p className="output-stale-note">当前编辑方案已更新，以上成片基于之前保存的版本。</p>}</section>
        <section className="output-path-section"><h3>输出路径</h3><div className="output-path"><code>{result?.outputPath || '应用方案后，输出路径会显示在这里。'}</code><button disabled={!result} onClick={() => void copyPath()}>复制路径 ↗</button></div></section>
        <section className="output-update"><h3>{result ? '需要更新成片？' : '准备生成成片'}</h3><p>{result ? '返回编辑保存新版方案，再手动应用生成成片。' : '确认方案后，点击上方按钮开始生成。'}</p><Button className="soft-button" block onClick={() => onNavigate('edit')}>返回方案编辑</Button>{result && !currentResult && <Button block className="download-previous" onClick={handleDownload}>下载上次成片</Button>}</section>
      </div></Panel>
    </div>}
  </>;
}
