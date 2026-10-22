import { useEffect, useRef, useState } from 'react';
import { Alert, App, Button, Form, Input, InputNumber, Select, Switch } from 'antd';
import { analyzeProject, getAnalysisFlags, getSavedPlan, getTask, type AnalyzeRequest } from '../api';
import AnalysisWarning from '../components/AnalysisWarning';
import { Banner, EmptyState, PageHeading, Panel, StatusPill } from '../components/StudioUI';
import { fileName, formatTime } from '../lib/format';
import { isTaskDone, savedPlanVersion, validatePlan } from '../lib/plan';
import { useProjectStore } from '../stores/projectStore';
import type { PageKey } from '../types/nav';

export default function AnalyzePage({ onNavigate }: { onNavigate: (page: PageKey) => void }) {
  const { message } = App.useApp();
  const { project, asset, task, plan, planVersions, analysisFlags: flags, demo, setTask, setPlan, setPlanVersions, setAnalysisFlags } = useProjectStore();
  const [form] = Form.useForm<AnalyzeRequest>();
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const qualityRef = useRef<HTMLDivElement>(null);
  const running = !!task && !isTaskDone(task);
  const review = task?.status === 'NEEDS_REVIEW' || !!flags?.simulated || flags?.qualityPassed === false;
  const completed = !!task && ['SUCCESS', 'NEEDS_REVIEW'].includes(task.status);

  useEffect(() => {
    if (!project || !task || demo) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const loadResult = async () => {
      const [planResult, flagResult] = await Promise.allSettled([getSavedPlan(project.projectId), getAnalysisFlags(project.projectId)]);
      if (cancelled) return;
      if (planResult.status === 'fulfilled') {
        const issue = validatePlan(planResult.value.plan);
        if (issue) setError(issue); else if (!useProjectStore.getState().planDirty) {
          setPlan(planResult.value.plan);
          setPlanVersions(planResult.value.versions);
        }
      } else setError('分析已结束，但读取方案失败。可点击“刷新任务”重试。');
      if (flagResult.status === 'fulfilled') setAnalysisFlags(flagResult.value);
      else setError('读取结果可信度失败，请刷新任务后再确认方案。');
    };
    const poll = async () => {
      try {
        const next = await getTask(task.taskId);
        if (cancelled) return;
        setTask(next);
        if (isTaskDone(next)) {
          if (next.status === 'FAILED') setError('分析失败，可调整目标后重新分析。');
          else await loadResult();
        } else timer = setTimeout(poll, 2000);
      } catch (err) { if (!cancelled) setError(`任务状态读取失败：${err instanceof Error ? err.message : String(err)}。请刷新任务重试。`); }
    };
    if (isTaskDone(task)) {
      if (task.status !== 'FAILED') void loadResult();
    } else void poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [project?.projectId, task?.taskId, demo, retry, setTask, setPlan, setAnalysisFlags]);

  const handleAnalyze = async () => {
    if (!project || running) return;
    const values = await form.validateFields();
    if (demo) { message.info('界面示例不会发起模型任务；退出示例模式后可使用真实项目。'); return; }
    setStarting(true); setError(null);
    try {
      const response = await analyzeProject(project.projectId, values);
      if (useProjectStore.getState().project?.projectId !== project.projectId) return;
      useProjectStore.setState({ plan: null, planVersions: [], planDirty: false, renderResult: null, renderedPlanVersion: null, renderedPlan: null, analysisFlags: null });
      setTask({ ...response, type: 'ANALYZE' });
      message.success('分析任务已启动');
    } catch (err) { setError(`发起分析失败：${err instanceof Error ? err.message : String(err)}`); }
    finally { setStarting(false); }
  };

  if (!project) return <><Banner title="先为源视频创建一个项目" description="上传素材后，就可以设定剪辑目标并发起分析。" trailing="步骤 2 / 4"/><PageHeading title="AI 分析" description="设定剪辑目标，跟踪任务状态，检查结果可信度"/><EmptyState title="还没有可分析的项目" description="在上传项目页创建项目并上传源视频。" action="去上传项目" onAction={() => onNavigate('upload')}/></>;
  const source = asset || plan?.source;
  const score = flags?.overallScore;
  const percent = Math.min(100, Math.max(0, Math.round(task?.progress || 0)));
  const qualityTitle = !flags?.qualityAvailable ? '暂无质量评审' : flags.qualityPassed === true ? '质量评审通过' : flags.qualityPassed === false ? '质量评审未通过' : '评审结果待确认';

  return <>
    {review ? <AnalysisWarning flags={flags} needsReview={review} onDetails={() => qualityRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })}/> : <Banner tone={completed ? 'success' : 'info'} title={completed ? '分析完成，剪辑方案已生成' : running ? '正在分析你的视频' : '设定剪辑目标，开始 AI 分析'} description={running ? '任务会持续更新进度；分析结束后，可查看方案和可信度。' : '你的画幅、时长、字幕和风格意图将用于生成剪辑方案。'} trailing="步骤 2 / 4"/>}
    <PageHeading title="AI 分析" description="设定剪辑目标，跟踪任务状态，检查结果可信度" actions={<><Button loading={starting || running} disabled={!asset && !plan} onClick={() => void handleAnalyze()}>{task ? '重新分析' : '开始分析'}</Button><Button type="primary" disabled={!plan || running} onClick={() => onNavigate('edit')}>查看方案</Button></>}/>
    {error && <Alert className="page-error" type="error" showIcon message={error} action={task ? <Button size="small" onClick={() => { setError(null); setRetry(retry + 1); }}>刷新任务</Button> : undefined}/>}
    <div className="analysis-layout">
      <Panel title="剪辑目标" extra={<span className="subtle">用户意图</span>} className="analysis-targets">
        <Form form={form} layout="vertical" requiredMark={false} initialValues={{ aspectRatio: '9:16', maxDuration: 60, addSubtitle: true, style: '快节奏口播' }} disabled={running || starting}>
          <div className="target-fields">
            <Form.Item name="aspectRatio" label="目标画幅"><Select aria-label="目标画幅" variant="borderless" options={[{ value: '9:16', label: '9:16  竖屏' }, { value: '16:9', label: '16:9  横屏' }, { value: '1:1', label: '1:1  方形' }, { value: '4:3', label: '4:3' }]}/></Form.Item>
            <Form.Item name="maxDuration" label="目标时长" rules={[{ required: true, message: '请输入目标时长' }]}><InputNumber aria-label="目标时长（秒）" variant="borderless" min={1} max={3600} suffix="秒"/></Form.Item>
            <Form.Item name="style" label="风格意图" rules={[{ required: true, whitespace: true, message: '请输入风格意图' }]}><Input aria-label="风格意图" variant="borderless" placeholder="如：快节奏口播"/></Form.Item>
            <Form.Item name="addSubtitle" label="生成字幕" valuePropName="checked"><Switch checkedChildren="开启" unCheckedChildren="关闭" aria-label="生成字幕"/></Form.Item>
          </div>
        </Form><p className="target-note">重新分析前可修改目标；系统保留原视频时间轴用于回查。</p>
      </Panel>
      <section className="source-project-panel"><span className="eyebrow">CURRENT PROJECT</span><h2>{project.title}</h2><div className="source-project-divider"/><small>源视频</small><strong className="mono source-name">{asset?.fileName || fileName(plan?.source.url)}</strong><p className="mono source-specs">{source?.duration ? formatTime(source.duration) : '—'}{source && source.width > 0 ? `  ·  ${source.width} × ${source.height}` : ''}{source?.fps ? `  ·  ${source.fps} FPS` : ''}</p><div className="source-project-footer"><span>{plan ? '已生成方案' : asset ? '已上传源视频' : '尚未上传'}</span><small className="mono">#{project.projectId}</small></div></section>
      <Panel className="analysis-task-panel"><div className="task-panel-header"><div><h2>分析任务</h2><p className="mono subtle">{task ? `任务 ID  #${task.taskId}` : '尚未发起任务'}</p></div><StatusPill status={task?.status || 'PENDING'}/></div>
        <div className="task-panel-content"><div className="task-progress-title"><h3>{completed ? '分析链路已结束' : task?.status === 'FAILED' ? '分析未完成' : running ? '分析进行中' : '准备开始分析'}</h3><strong className="mono">{percent}%</strong></div><div className={`task-progress-track ${task?.status === 'FAILED' ? 'failed' : ''}`}><div style={{ width: `${percent}%` }}/></div>
          <h4>流程记录</h4><div className="pipeline-steps">{[{ title: '01 视频分析', text: completed ? '流程已结束' : running ? '处理中' : task?.status === 'FAILED' ? '未完成' : '等待开始', done: completed }, { title: '02 生成方案', text: plan ? `Plan v${savedPlanVersion(plan, planVersions)}` : '等待方案', done: !!plan }, { title: '03 质量审核', text: flags?.qualityAvailable ? flags.qualityPassed ? '评审通过' : '需人工复核' : '等待评审', done: !!flags?.qualityPassed }].map((step) => <div className={`pipeline-step ${step.done ? 'done' : ''} ${step.title.startsWith('03') && review ? 'warning' : ''}`} key={step.title}><i/><div><strong>{step.title}</strong><span>{step.text}</span></div></div>)}</div>
          <div className="task-next"><Button type="primary" disabled={!plan || running} onClick={() => onNavigate('edit')}>进入方案编辑 →</Button><span>先核对原视频时间与提示项，再保存方案。</span></div>
        </div>
      </Panel>
      <div ref={qualityRef}><Panel title="可信度与质量" extra={<span className="subtle">本次分析结果</span>} className="analysis-quality-panel"><div className="quality-content"><div className={`quality-score ${flags?.qualityPassed ? 'passed' : ''}`}><strong className="mono">{score != null ? score.toFixed(2) : '—'}</strong><div><b>{qualityTitle}</b><small className="mono">总分 / 1.00</small></div></div><div className="quality-track"><div style={{ width: `${Math.max(0, Math.min(1, score ?? 0)) * 100}%` }}/></div><div className={`provenance-summary ${flags?.simulated ? 'warning' : ''}`}><strong>{flags ? flags.simulated ? '使用了模拟 / 降级数据' : '未标记模拟 / 降级数据' : '等待分析可信度结果'}</strong><span>{flags?.simulated ? '场景描述与重要度仅供参考' : '可信度与质量评审结果分别展示'}</span></div><div className="quality-advice"><strong>建议核对</strong><p>原视频时间 · 片段保留 · 字幕文本</p><small>任务完成与质量通过分别确认</small></div></div></Panel></div>
    </div>
  </>;
}
