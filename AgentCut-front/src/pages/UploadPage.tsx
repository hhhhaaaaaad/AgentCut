import { useState } from 'react';
import { Alert, App, Button, Form, Input, Progress, Upload } from 'antd';
import { createProject, uploadVideo, type CreateProjectRequest } from '../api';
import { Banner, PageHeading, Panel, StatusPill } from '../components/StudioUI';
import { formatSize, formatTime, readVideoMetadata } from '../lib/format';
import { useProjectStore } from '../stores/projectStore';
import type { PageKey } from '../types/nav';

export default function UploadPage({ onNavigate }: { onNavigate: (page: PageKey) => void }) {
  const { message } = App.useApp();
  const { project, asset, demo, uploading, uploadProgress, setUploading, setUploadProgress, setProject, setAsset } = useProjectStore();
  const [form] = Form.useForm<CreateProjectRequest>();
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleCreate = async (values: CreateProjectRequest) => {
    if (uploading) return;
    setCreating(true);
    setError(null);
    try {
      const created = demo ? { projectId: `demo-${Date.now()}`, title: values.title.trim(), status: 'DRAFT', userId: values.userId } : await createProject({ title: values.title.trim(), userId: values.userId?.trim() || undefined });
      setProject(created);
      message.success(`项目已创建：${created.title}`);
    } catch (err) { setError(`创建项目失败：${err instanceof Error ? err.message : String(err)}`); }
    finally { setCreating(false); }
  };

  const handleUpload = async (file: File) => {
    if (!project || uploading || creating) return;
    if (!file.type.startsWith('video/') && !/\.(mp4|mov|m4v|mkv|webm|avi)$/i.test(file.name)) {
      message.error('请选择视频文件'); return;
    }
    setUploading(true); setUploadProgress(0); setError(null);
    try {
      const metadata = await readVideoMetadata(file);
      const uploaded = demo ? { assetId: `demo-${Date.now()}`, projectId: project.projectId, type: 'SOURCE', ossUrl: '', fileName: file.name, size: file.size, fps: 0, ...metadata } : await uploadVideo(project.projectId, file, setUploadProgress);
      if (useProjectStore.getState().project?.projectId !== project.projectId) return;
      setAsset({ ...uploaded, duration: uploaded.duration || metadata.duration, width: uploaded.width || metadata.width, height: uploaded.height || metadata.height }, URL.createObjectURL(file));
      setUploadProgress(100);
      message.success(`视频上传成功：${file.name}`);
    } catch (err) { const failure = `上传失败：${err instanceof Error ? err.message : String(err)}，可重新选择文件重试。`; setError(failure); message.error(failure); }
    finally { setUploading(false); }
  };

  return <>
    <Banner title={asset ? '源视频已上传，可以开始 AI 分析' : project ? '项目已创建，可以上传源视频' : '从一个视频，开始你的剪辑项目'} description={asset ? '素材已保存，将作为后续分析和剪辑的时间基准。' : '先创建项目，再上传一个源视频，设定你的剪辑目标。'} trailing="步骤 1 / 4"/>
    <PageHeading title="上传项目" description="创建项目，上传源视频，开始一条可追溯的剪辑流程" actions={<><Button disabled={uploading || creating} onClick={() => { form.resetFields(); document.querySelector<HTMLInputElement>('#project-title')?.focus(); }}>新建项目</Button><Button type="primary" disabled={!project || !asset || uploading} onClick={() => onNavigate('analyze')}>开始 AI 分析</Button></>}/>
    {error && <Alert className="page-error" type="error" showIcon closable onClose={() => setError(null)} message={error}/>}
    <div className="upload-layout">
      <div className="upload-left">
        <Panel className="create-project-panel"><h2>创建项目</h2><p className="panel-description">为这次剪辑建立独立的项目空间。</p>
          <Form form={form} disabled={uploading || creating} layout="vertical" initialValues={{ title: '我的剪辑项目' }} onFinish={handleCreate} requiredMark={false}>
            <Form.Item name="title" label="项目名称" rules={[{ required: true, whitespace: true, message: '请输入项目名称' }, { max: 100, message: '项目名称最多 100 字' }]}><Input id="project-title" placeholder="例如：旅行 Vlog 剪辑"/></Form.Item>
            <Form.Item name="userId" label="用户 ID · 可选"><Input placeholder="留空使用默认用户"/></Form.Item>
            <div className="form-actions"><Button htmlType="submit" type="text" className="soft-button" loading={creating}>创建项目</Button></div>
          </Form>
        </Panel>
        <Panel title="当前项目" extra={project && <StatusPill status={project.status || 'DRAFT'}/>} className="project-overview">
          {project ? <div className="project-overview-body"><small>项目标题</small><h3>{project.title}</h3><small>项目 ID</small><p className="mono">{project.projectId}</p><div className="project-asset-count">源素材 <b className="mono">{asset ? '01' : '00'}</b> 个</div><p className="subtle">视频上传完成后，即可发起分析任务。</p></div> : <div className="project-overview-body project-empty"><span className="empty-project-symbol">＋</span><p>还没有当前项目</p><small>在上方填写名称并创建项目。</small></div>}
        </Panel>
      </div>
      <Panel className="upload-panel"><div className="upload-title"><div><h2>上传源视频</h2><p className="panel-description">选择一个视频文件，自动保存到当前项目。</p></div><span className="small-label">单个源视频</span></div>
        <Upload.Dragger className="source-dropzone" accept="video/*,.mkv,.avi" multiple={false} disabled={!project || uploading || creating} showUploadList={false} beforeUpload={(file) => { void handleUpload(file); return false; }}>
          <div className="upload-arrow" aria-hidden>↑</div><h3>{uploading ? '视频上传中…' : '拖拽视频到这里'}</h3><p>{project ? '或点击选择文件 · 上传后自动保存到项目' : '请先创建项目，再选择源视频'}</p><small>支持常见视频格式</small>
        </Upload.Dragger>
        {uploading && <Progress className="upload-progress" percent={uploadProgress} size="small"/>}
        <h4 className="uploaded-label">已上传文件</h4>
        {asset ? <div className="uploaded-file"><div className="file-extension">{asset.fileName.split('.').pop()?.toUpperCase().slice(0, 4) || 'VIDEO'}</div><div className="file-copy"><strong className="mono" title={asset.fileName}>{asset.fileName}</strong><span className="mono">{formatSize(asset.size)}{asset.duration > 0 && `  ·  ${formatTime(asset.duration)}`}{asset.width > 0 && `  ·  ${asset.width} × ${asset.height}`}</span></div><span className="status-pill pill-success">已上传</span></div> : <div className="uploaded-file file-empty"><span>暂无源视频</span><small>选择视频后，文件信息会显示在这里。</small></div>}
        <div className="upload-footnotes"><p>当前支持单个视频文件上传，请等待上传完成后再离开。</p><p>下一步：进入 AI 分析，设定画幅、时长、字幕和风格意图。</p></div>
      </Panel>
    </div>
  </>;
}
