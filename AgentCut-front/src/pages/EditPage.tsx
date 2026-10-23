import { useEffect, useRef, useState } from 'react';
import { Alert, App, Button, Drawer, Dropdown, Input, InputNumber, Select, Spin, Switch } from 'antd';
import { getAnalysisFlags, getSavedPlan, savePlan } from '../api';
import AnalysisWarning from '../components/AnalysisWarning';
import { MediaPreview } from '../components/MediaPreview';
import { Banner, EmptyState, PageHeading, Panel } from '../components/StudioUI';
import { aspectRatio, fileName, formatTime, mediaUrl, parseTime } from '../lib/format';
import { outputDuration, savedPlanVersion, validatePlan } from '../lib/plan';
import { useProjectStore } from '../stores/projectStore';
import type { PageKey } from '../types/nav';
import { createOperation, OPERATION_LABELS, type Global, type Operation, type OperationType, type Plan, type Segment } from '../types/plan';

export default function EditPage({ onNavigate }: { onNavigate: (page: PageKey) => void }) {
  const { message, modal } = App.useApp();
  const { project, plan, planVersions, planDirty, analysisFlags, asset, sourcePreviewUrl, demo, task, setPlan, setPlanVersions, editPlan, setAnalysisFlags } = useProjectStore();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedNeedsRefresh, setSavedNeedsRefresh] = useState(false);
  const removedOperations = useRef(new Map<string, Operation[]>());
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [selectedId, setSelectedId] = useState(demo ? 'seg_002' : '');
  const [time, setTime] = useState(demo ? 21.4 : 0);
  const [globalOpen, setGlobalOpen] = useState(false);
  const [jsonOpen, setJsonOpen] = useState(false);
  const [jsonText, setJsonText] = useState('');
  const selected = plan?.timeline.find((segment) => segment.id === selectedId) || plan?.timeline[0];
  const issue = plan ? validatePlan(plan) : null;
  const review = task?.status === 'NEEDS_REVIEW' || !!analysisFlags?.simulated || analysisFlags?.qualityPassed === false;

  useEffect(() => {
    if (!project || demo) return;
    let cancelled = false;
    if (!plan) {
      setLoading(true);
      getSavedPlan(project.projectId).then(({ plan: value, versions }) => {
        if (cancelled) return;
        const invalid = validatePlan(value);
        if (invalid) setError(invalid); else { setPlan(value); setPlanVersions(versions); setError(null); }
      }).catch((err) => { if (!cancelled) setError(`加载方案失败：${err instanceof Error ? err.message : String(err)}`); })
        .finally(() => { if (!cancelled) setLoading(false); });
    }
    if (!analysisFlags) getAnalysisFlags(project.projectId).then((flags) => { if (!cancelled) setAnalysisFlags(flags); }).catch(() => {});
    return () => { cancelled = true; };
  }, [project?.projectId, demo, retry, setPlan, setAnalysisFlags]);

  const updateSegment = (patch: Partial<Segment>) => {
    if (!plan || !selected) return;
    editPlan({ ...plan, timeline: plan.timeline.map((segment) => segment.id === selected.id ? { ...segment, ...patch } : segment) });
  };
  const updateOperation = (index: number, operation: Operation) => updateSegment({ operations: selected?.operations?.map((value, i) => i === index ? operation : value) });
  const addOperation = (type: OperationType) => {
    if (!selected || !selected.keep || !plan) return;
    const operation = createOperation(type);
    if (operation.type === 'subtitle') { operation.start = 0; operation.end = outputDuration([selected]); }
    if (operation.type === 'crop') { operation.width = Math.min(plan.global.output.width, plan.source.width); operation.height = Math.min(plan.global.output.height, plan.source.height); }
    const operations = [...(selected.operations || [])];
    const speedIndex = operations.findIndex((value) => value.type === 'speed');
    operations.splice(operation.type !== 'speed' && speedIndex >= 0 ? speedIndex : operations.length, 0, operation);
    updateSegment({ operations });
  };
  const toggleKeep = (keep: boolean) => {
    if (!selected) return;
    if (!keep) removedOperations.current.set(selected.id, selected.operations || []);
    updateSegment({ keep, operations: keep ? removedOperations.current.get(selected.id) || [] : [] });
  };
  const addSegment = () => {
    if (!plan) return;
    const lastEnd = plan.timeline[plan.timeline.length - 1]?.sourceRange.end || 0;
    const start = lastEnd >= plan.source.duration ? 0 : lastEnd;
    const end = plan.source.duration > 0 ? Math.min(start + 5, plan.source.duration) : start + 5;
    const segment: Segment = { id: `seg_${crypto.randomUUID().replace(/-/g, '').slice(0, 8)}`, keep: true, sourceRange: { start, end }, operations: [] };
    editPlan({ ...plan, timeline: [...plan.timeline, segment] });
    setSelectedId(segment.id); setTime(start);
  };
  const removeSegment = () => {
    if (!plan || !selected) return;
    editPlan({ ...plan, timeline: plan.timeline.filter((value) => value.id !== selected.id), transitions: plan.transitions?.filter((value) => value.from !== selected.id && value.to !== selected.id) });
  };
  const moveSegment = (direction: number) => {
    if (!plan || !selected) return;
    const from = plan.timeline.indexOf(selected), to = from + direction;
    if (to < 0 || to >= plan.timeline.length) return;
    const timeline = [...plan.timeline];
    [timeline[from], timeline[to]] = [timeline[to], timeline[from]];
    editPlan({ ...plan, timeline });
  };
  const handleSave = async () => {
    if (!plan || !project) return;
    if (issue) { setError(issue); return; }
    setSaving(true); setError(null);
    try {
      if (demo) {
        const version = (savedPlanVersion(plan, planVersions) || 0) + 1;
        setPlan({ ...plan, planVersion: version });
        setPlanVersions([...planVersions, String(version)]);
      }
      else {
        await savePlan(project.projectId, plan);
        if (useProjectStore.getState().project?.projectId !== project.projectId) return;
        setPlan(plan);
        try {
          const { plan: refreshed, versions } = await getSavedPlan(project.projectId);
          if (useProjectStore.getState().project?.projectId !== project.projectId) return;
          const invalid = validatePlan(refreshed);
          if (invalid) throw new Error(invalid);
          setPlan(refreshed);
          setPlanVersions(versions);
        } catch {
          setSavedNeedsRefresh(true);
          setError('方案已保存，但刷新版本失败。请先重新加载方案。');
          return;
        }
      }
      message.success(demo ? '示例方案已在当前页面保存' : '方案已保存为新版本');
    } catch (err) { setError(`保存方案失败：${err instanceof Error ? err.message : String(err)}`); }
    finally { setSaving(false); }
  };
  let jsonIssue: string | null = null;
  try { const parsed = JSON.parse(jsonText || '{}'); jsonIssue = validatePlan(parsed); if (!jsonIssue && parsed.projectId !== project?.projectId) jsonIssue = 'JSON 中的 projectId 必须与当前项目一致'; }
  catch (err) { jsonIssue = err instanceof Error ? err.message : 'JSON 格式有误'; }

  return <>
    {review ? <AnalysisWarning flags={analysisFlags} needsReview={review} onDetails={() => onNavigate('analyze')}/> : <Banner title={planDirty ? '方案有未保存修改' : '方案已就绪，可以开始编辑'} description="核对原视频时间，调整保留片段与操作，保存后生成新版本。" trailing="步骤 3 / 4"/>}
    <PageHeading title="方案编辑" badge={plan && <span className="version-badge mono">v{savedPlanVersion(plan, planVersions)}</span>} description="将分析结果整理成可回查、可编辑的剪辑方案" actions={<><Button disabled={!plan || saving} onClick={() => { setJsonText(JSON.stringify(plan, null, 2)); setJsonOpen(true); }}>查看 JSON</Button><Button type="primary" disabled={!plan || !!issue || loading || savedNeedsRefresh} loading={saving} onClick={() => void handleSave()}>保存方案{planDirty ? ' ·' : ''}</Button></>}/>
    {(error || issue) && <Alert className="page-error" type="error" showIcon message={error || issue} action={(!plan || savedNeedsRefresh) && project ? <Button size="small" onClick={() => { setPlan(null); setSavedNeedsRefresh(false); setRetry(retry + 1); }}>重新加载</Button> : undefined}/>}
    <Spin spinning={loading || saving}>
      {!project || !plan ? <EmptyState title={project ? '还没有可编辑的方案' : '还没有当前项目'} description={project ? '在 AI 分析页发起分析，生成初稿后在这里编辑。' : '先创建项目并上传源视频，再生成剪辑方案。'} action={project ? '去 AI 分析' : '去上传项目'} onAction={() => onNavigate(project ? 'analyze' : 'upload')}/> : <div className="editor-layout"><div className="editor-main-column">
        <MediaPreview src={demo ? undefined : sourcePreviewUrl || mediaUrl(asset?.ossUrl) || mediaUrl(plan.source.url)} demo={demo} fileName={asset?.fileName || fileName(plan.source.url)} segmentId={selected?.id} duration={plan.source.duration || asset?.duration || 0} currentTime={time} onTimeChange={setTime} ratio={aspectRatio(plan.global.output.width, plan.global.output.height)}/>
        <Timeline plan={plan} selectedId={selected?.id} currentTime={time} demo={demo} onSelect={(segment) => { setSelectedId(segment.id); setTime(segment.sourceRange.start); }} onAdd={addSegment}/>
      </div><Panel className="segment-inspector" title="片段属性" extra={<div className="inspector-extra"><span className="mono subtle">{selected?.id || '—'}</span><Dropdown trigger={['click']} menu={{ items: [{ key: 'previous', label: '前移片段', disabled: !selected || plan.timeline.indexOf(selected) === 0, onClick: () => moveSegment(-1) }, { key: 'next', label: '后移片段', disabled: !selected || plan.timeline.indexOf(selected) === plan.timeline.length - 1, onClick: () => moveSegment(1) }, { key: 'delete', label: '删除片段', danger: true, disabled: !selected, onClick: () => modal.confirm({ title: '删除该片段？', content: '保存方案前可通过重新加载撤销此修改。', onOk: removeSegment }) }] }}><Button type="text" size="small" aria-label="片段更多操作">···</Button></Dropdown></div>}>
        {selected ? <div className="inspector-content"><div className="keep-control"><strong>保留此片段</strong><Switch aria-label="保留此片段" checked={selected.keep} onChange={toggleKeep}/></div>
          <section className="range-section"><h3>源时间区间</h3><p>全部使用原视频全局时间 · 秒</p><div className="range-inputs"><label>开始<InputNumber aria-label="片段开始时间" formatter={(value, info) => info.userTyping ? info.input : formatTime(Number(value), true)} parser={parseTime} min={0} max={plan.source.duration || undefined} step={.1} value={selected.sourceRange.start} onChange={(value) => { if (value != null) updateSegment({ sourceRange: { ...selected.sourceRange, start: value } }); }}/></label><label>结束<InputNumber aria-label="片段结束时间" formatter={(value, info) => info.userTyping ? info.input : formatTime(Number(value), true)} parser={parseTime} min={0} max={plan.source.duration || undefined} step={.1} value={selected.sourceRange.end} onChange={(value) => { if (value != null) updateSegment({ sourceRange: { ...selected.sourceRange, end: value } }); }}/></label></div></section>
          <section className="operations-section"><div className="inspector-section-heading"><h3>段内操作</h3><span className="mono">{String(selected.operations?.length || 0).padStart(2, '0')}</span></div><div className="operations-list">{(selected.operations || []).map((operation, index) => <OperationEditor key={`${selected.id}-${index}-${operation.type}`} operation={operation} onChange={(value) => updateOperation(index, value)} onRemove={() => updateSegment({ operations: selected.operations?.filter((_, i) => i !== index) })}/>)}{!selected.operations?.length && <p className="subtle operation-empty">尚未添加段内操作</p>}</div><Dropdown trigger={['click']} menu={{ items: (Object.keys(OPERATION_LABELS) as OperationType[]).map((type) => ({ key: type, label: OPERATION_LABELS[type], onClick: () => addOperation(type) })) }}><Button disabled={!selected.keep} className="soft-button add-operation">+ 添加操作</Button></Dropdown></section>
          <button className="global-summary" onClick={() => setGlobalOpen(true)}><h3>全局输出 <span>↗</span></h3><p className="mono">{aspectRatio(plan.global.output.width, plan.global.output.height)} · {plan.global.output.width} × {plan.global.output.height} · {plan.global.output.fps} fps</p><p>字幕 {plan.global.subtitleStyle ? '开启' : '未设置'}　背景音乐 {plan.global.bgm ? '已设置' : '未设置'}</p></button>
          <p className="inspector-note">修改后请保存方案，生成新版本。</p>
        </div> : <EmptyState title="暂无片段" description="点击“新增片段”开始编辑。"/>}
      </Panel></div>}
    </Spin>
    <Drawer title="方案 JSON" width={660} open={jsonOpen} onClose={() => setJsonOpen(false)} extra={<Button onClick={() => { try { setJsonText(JSON.stringify(JSON.parse(jsonText), null, 2)); } catch { message.error('请先修正 JSON 格式'); } }}>格式化</Button>} footer={<div className="drawer-actions"><Button onClick={() => setJsonOpen(false)}>取消</Button><Button type="primary" disabled={!!jsonIssue} onClick={() => { editPlan(JSON.parse(jsonText) as Plan); setJsonOpen(false); }}>应用到编辑器</Button></div>}>
      <p className="drawer-description">编辑完整 Plan 文档，通过校验后应用到编辑器，再点击保存方案。</p><textarea className={`json-editor ${jsonIssue ? 'invalid' : ''}`} value={jsonText} onChange={(event) => setJsonText(event.target.value)} spellCheck={false} aria-label="方案 JSON"/>{jsonIssue ? <Alert type="error" showIcon message="JSON 尚不可应用" description={jsonIssue}/> : <Alert type="success" showIcon message="结构校验通过，可应用到编辑器"/>}
    </Drawer>
    {plan && <GlobalSettings open={globalOpen} onClose={() => setGlobalOpen(false)} value={plan.global} onChange={(global) => editPlan({ ...plan, global })}/>}
  </>;
}

function Timeline({ plan, selectedId, currentTime, demo, onSelect, onAdd }: { plan: Plan; selectedId?: string; currentTime: number; demo: boolean; onSelect: (segment: Segment) => void; onAdd: () => void }) {
  const total = plan.timeline.reduce((sum, segment) => sum + Math.max(.1, segment.sourceRange.end - segment.sourceRange.start), 0);
  let before = 0, playhead = 0;
  for (const segment of plan.timeline) {
    const length = Math.max(.1, segment.sourceRange.end - segment.sourceRange.start);
    if (segment.id === selectedId) playhead = (before + Math.min(length, Math.max(0, currentTime - segment.sourceRange.start))) / total * 100;
    before += length;
  }
  return <Panel className="timeline-panel"><div className="timeline-heading"><h2>剪辑时间线</h2><span>{plan.timeline.length} 段 · 保留 {plan.timeline.filter((segment) => segment.keep).length} 段 · 预计 {formatTime(outputDuration(plan.timeline))}</span><Button size="small" className="soft-button" onClick={onAdd}>+ 新增片段</Button></div>
    <div className="timeline-content"><div className="timeline-ruler">{[0, .25, .5, .75, 1].map((fraction) => <span key={fraction}>{formatTime(plan.source.duration * fraction)}<i/></span>)}</div><small className="track-label">VIDEO 01</small><div className="timeline-scroll"><div className="timeline-lane">{plan.timeline.map((segment) => <button className={`timeline-segment ${segment.id === selectedId ? 'selected' : ''} ${!segment.keep ? 'removed' : ''}`} key={segment.id} aria-pressed={segment.id === selectedId} aria-label={`${segment.id}，${segment.keep ? '保留' : '删除'}，${formatTime(segment.sourceRange.start, true)}至${formatTime(segment.sourceRange.end, true)}`} style={{ flexGrow: Math.max(.1, segment.sourceRange.end - segment.sourceRange.start) }} onClick={() => onSelect(segment)}><strong className="mono">{segment.id}</strong><span className="mono">{formatTime(segment.sourceRange.start, true)}—{formatTime(segment.sourceRange.end, true)}</span></button>)}{plan.timeline.length > 0 && <div className="timeline-playhead" style={{ left: `${playhead}%` }}><i/></div>}</div></div><small className="track-label audio-label">AUDIO 01{demo ? ' · 示例音轨' : ''}</small><div className={`audio-track ${demo ? '' : 'audio-pending'}`}>{demo ? Array.from({ length: 78 }, (_, index) => <i key={index} style={{ height: `${4 + ((index * 19 + index * index * 3) % 17)}px` }}/>) : <span>音频波形尚未生成 · 可在上方预览源视频</span>}</div><p className="timeline-note">片段按输出顺序排列 · 标签显示原视频全局时间</p></div>
  </Panel>;
}

function OperationEditor({ operation, onChange, onRemove }: { operation: Operation; onChange: (operation: Operation) => void; onRemove: () => void }) {
  const summary = operation.type === 'subtitle' ? operation.text || '尚未填写字幕' : operation.type === 'speed' ? `${operation.rate}× 变速` : operation.type === 'volume' ? `音量 ${Math.round(operation.volume * 100)}%` : operation.type === 'crop' ? `${operation.width} × ${operation.height}` : '关闭此片段声音';
  return <details className="operation-item"><summary><strong>{OPERATION_LABELS[operation.type]}</strong><span>{summary}</span></summary><div className="operation-fields">
    {operation.type === 'subtitle' && <><label>字幕文本<Input.TextArea aria-label="字幕文本" autoSize={{ minRows: 2, maxRows: 5 }} value={operation.text} onChange={(event) => onChange({ ...operation, text: event.target.value })}/></label><div className="two-fields"><label>段内开始（秒）<InputNumber min={0} value={operation.start} onChange={(value) => value != null && onChange({ ...operation, start: value })}/></label><label>段内结束（秒）<InputNumber min={0} value={operation.end} onChange={(value) => value != null && onChange({ ...operation, end: value })}/></label></div></>}
    {operation.type === 'speed' && <label>播放倍速<InputNumber min={.1} max={16} step={.1} value={operation.rate} onChange={(value) => value != null && onChange({ ...operation, rate: value })}/></label>}
    {operation.type === 'volume' && <label>音量（0—1）<InputNumber min={0} max={1} step={.1} value={operation.volume} onChange={(value) => value != null && onChange({ ...operation, volume: value })}/></label>}
    {operation.type === 'crop' && <div className="two-fields">{(['x', 'y', 'width', 'height'] as const).map((field) => <label key={field}>{({ x: '左侧', y: '顶部', width: '宽度', height: '高度' })[field]}<InputNumber min={field === 'x' || field === 'y' ? 0 : 1} value={operation[field]} onChange={(value) => value != null && onChange({ ...operation, [field]: value })}/></label>)}</div>}
    {operation.type === 'mute' && <p className="subtle">此片段的原始声音将静音。</p>}
    <Button danger type="text" size="small" onClick={onRemove}>移除此操作</Button>
  </div></details>;
}

function GlobalSettings({ open, onClose, value, onChange }: { open: boolean; onClose: () => void; value: Global; onChange: (value: Global) => void }) {
  return <Drawer title="全局输出设置" open={open} onClose={onClose} width={420}><div className="settings-fields"><h3>输出视频</h3><div className="two-fields">{(['width', 'height', 'fps'] as const).map((field) => <label key={field}>{({ width: '宽度', height: '高度', fps: '帧率' })[field]}<InputNumber min={1} value={value.output[field]} onChange={(number) => number != null && onChange({ ...value, output: { ...value.output, [field]: number } })}/></label>)}<label>编码器<Input value={value.output.codec || 'libx264'} onChange={(event) => onChange({ ...value, output: { ...value.output, codec: event.target.value } })}/></label></div><label>码率（可选）<Input placeholder="例如：4M" value={value.output.bitrate || ''} onChange={(event) => onChange({ ...value, output: { ...value.output, bitrate: event.target.value || undefined } })}/></label><div className="settings-section-heading"><h3>字幕样式</h3><Switch aria-label="启用字幕样式" checked={!!value.subtitleStyle} onChange={(enabled) => onChange({ ...value, subtitleStyle: enabled ? { fontSize: 48, color: '#FFFFFF', position: 'bottom' } : undefined })}/></div>{value.subtitleStyle && <><label>字号<InputNumber min={1} value={value.subtitleStyle.fontSize} onChange={(fontSize) => fontSize != null && onChange({ ...value, subtitleStyle: { ...value.subtitleStyle, fontSize } })}/></label><label>颜色<Input value={value.subtitleStyle.color || '#FFFFFF'} onChange={(event) => onChange({ ...value, subtitleStyle: { ...value.subtitleStyle, color: event.target.value } })}/></label><label>位置<Select value={value.subtitleStyle.position || 'bottom'} options={[{ value: 'top', label: '顶部' }, { value: 'center', label: '居中' }, { value: 'bottom', label: '底部' }]} onChange={(position) => onChange({ ...value, subtitleStyle: { ...value.subtitleStyle, position } })}/></label></>}<div className="settings-section-heading"><h3>背景音乐</h3><Switch aria-label="启用背景音乐" checked={!!value.bgm} onChange={(enabled) => onChange({ ...value, bgm: enabled ? { url: '', volume: .3, loop: true } : undefined })}/></div>{value.bgm && <><label>音乐地址<Input value={value.bgm.url} placeholder="https://…" onChange={(event) => onChange({ ...value, bgm: { ...value.bgm!, url: event.target.value } })}/></label><label>音量<InputNumber min={0} max={1} step={.1} value={value.bgm.volume ?? .3} onChange={(volume) => volume != null && onChange({ ...value, bgm: { ...value.bgm!, volume } })}/></label><label>循环播放<Switch checked={value.bgm.loop ?? true} onChange={(loop) => onChange({ ...value, bgm: { ...value.bgm!, loop } })}/></label></>}<p className="subtle">设置会同步到编辑器，请在关闭后保存方案。</p></div></Drawer>;
}
