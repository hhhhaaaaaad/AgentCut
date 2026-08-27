import { useState } from 'react';
import { App, Button, Card, Descriptions, Empty, Space, Tag, Typography } from 'antd';
import { applyPlan, getPlan, type ApplyResult } from '../api';
import { useProjectStore } from '../stores/projectStore';
import type { PageKey } from '../types/nav';

interface Props {
  onNavigate?: (page: PageKey) => void;
}

/** 秒数 → 友好时长 */
function formatDuration(seconds: number): string {
  if (!seconds || seconds < 0) return '-';
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m} 分 ${s} 秒`;
}

/** 字节数 → 友好大小 */
function formatSize(bytes: number): string {
  if (!bytes || bytes < 0) return '-';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/**
 * 预览 / 导出页：应用方案（apply）→ 展示成片 outputPath + 下载入口。
 */
export default function PreviewPage({ onNavigate }: Props) {
  const { message } = App.useApp();
  const { project, plan } = useProjectStore();

  const [applying, setApplying] = useState(false);
  const [result, setResult] = useState<ApplyResult | null>(null);

  const handleApply = async () => {
    if (!project) return;
    setApplying(true);
    try {
      const res = await applyPlan(project.projectId);
      setResult(res);
      message.success('方案已应用，成片生成完成。');
      // 刷新方案状态（后端可能将 plan.status 置为 APPLIED）
      try {
        await getPlan(project.projectId);
      } catch {
        /* 忽略：仅刷新，失败不影响展示 */
      }
    } catch (err) {
      message.error(`应用方案失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setApplying(false);
    }
  };

  const handleDownload = () => {
    if (!result) return;
    if (/^https?:\/\//.test(result.outputPath)) {
      window.open(result.outputPath, '_blank');
    } else {
      // 内部存储路径（oss://… 或本地相对路径）需后端提供下载/直链接口
      message.info('后端下载直链接口未开放，当前 outputPath 为内部存储路径。');
    }
  };

  if (!project) {
    return (
      <Card size="small">
        <Empty description="请先在「上传项目」页创建项目并完成分析。" />
      </Card>
    );
  }

  const keepCount = plan ? plan.timeline.filter((s) => s.keep).length : 0;

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <Card
        title="应用方案"
        size="small"
        extra={<Typography.Text type="secondary">项目：{project.title}</Typography.Text>}
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Descriptions column={4} size="small" bordered>
            <Descriptions.Item label="方案版本">{plan?.planVersion ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="片段总数">{plan?.timeline.length ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="保留片段">{keepCount}</Descriptions.Item>
            <Descriptions.Item label="输出尺寸">
              {plan ? `${plan.global.output.width} × ${plan.global.output.height}` : '-'}
            </Descriptions.Item>
          </Descriptions>
          <Button type="primary" size="large" loading={applying} onClick={handleApply}>
            {applying ? '渲染中…' : '应用方案（生成成片）'}
          </Button>
          {plan?.planVersion && (
            <Typography.Text type="secondary">
              提示：apply 会按当前方案 v{plan.planVersion} 触发 FFmpeg 渲染，请先在「方案编辑」页确认方案内容。
            </Typography.Text>
          )}
        </Space>
      </Card>

      {result && (
        <Card title="成片结果" size="small">
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <Descriptions column={3} size="small" bordered>
              <Descriptions.Item label="时长">{formatDuration(result.duration)}</Descriptions.Item>
              <Descriptions.Item label="大小">{formatSize(result.size)}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color="success">APPLIED</Tag>
              </Descriptions.Item>
            </Descriptions>
            <div>
              <Typography.Text strong>输出路径：</Typography.Text>
              <Typography.Text code copyable={{ text: result.outputPath }}>
                {result.outputPath}
              </Typography.Text>
            </div>
            <Space>
              <Button onClick={handleDownload}>下载成片</Button>
              {onNavigate && <Button onClick={() => onNavigate('edit')}>返回编辑方案</Button>}
            </Space>
          </Space>
        </Card>
      )}
    </Space>
  );
}
