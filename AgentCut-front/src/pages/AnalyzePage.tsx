import { useEffect, useRef, useState } from 'react';
import {
  App, Button, Card, Empty, Form, Input, InputNumber, Progress, Select, Space, Switch, Tag, Typography,
} from 'antd';
import { analyzeProject, getPlan, getTask, type AnalyzeRequest, type Task } from '../api';
import { useProjectStore } from '../stores/projectStore';
import type { PageKey } from '../types/nav';

/** 任务状态 → Tag 颜色 */
const STATUS_COLOR: Record<string, string> = {
  PENDING: 'default',
  RUNNING: 'processing',
  RETRYING: 'warning',
  SUCCESS: 'success',
  FAILED: 'error',
};

const DONE_STATUS = new Set(['SUCCESS', 'FAILED']);

interface Props {
  onNavigate?: (page: PageKey) => void;
}

/**
 * 分析页：填写用户意图（画幅 / 时长 / 字幕 / 风格）→ 触发 analyze → 轮询任务进度。
 */
export default function AnalyzePage({ onNavigate }: Props) {
  const { message } = App.useApp();
  const { project, task, setTask, setPlan } = useProjectStore();
  const [form] = Form.useForm<AnalyzeRequest>();
  const [starting, setStarting] = useState(false);
  const [polling, setPolling] = useState(false);
  const timerRef = useRef<number | null>(null);

  const stopPolling = () => {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
    setPolling(false);
  };

  useEffect(() => () => stopPolling(), []);

  const handleAnalyze = async () => {
    if (!project) return;
    const values = await form.validateFields();
    setStarting(true);
    try {
      const res = await analyzeProject(project.projectId, {
        aspectRatio: values.aspectRatio,
        maxDuration: values.maxDuration,
        addSubtitle: values.addSubtitle,
        style: values.style,
      });
      setTask({ taskId: res.taskId, status: res.status, progress: res.progress });
      message.success(`分析任务已启动：${res.taskId}`);
      startPolling(res.taskId);
    } catch (err) {
      message.error(`发起分析失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setStarting(false);
    }
  };

  const startPolling = (taskId: string) => {
    stopPolling();
    setPolling(true);
    timerRef.current = window.setInterval(async () => {
      try {
        const t: Task = await getTask(taskId);
        setTask(t);
        if (DONE_STATUS.has(t.status)) {
          stopPolling();
          if (t.status === 'SUCCESS') {
            message.success('分析完成，方案已生成，可前往编辑页查看。');
            // 顺手把方案拉进 store，编辑页可直接展示
            try {
              setPlan(await getPlan(project!.projectId));
            } catch {
              /* 方案接口暂不可用时忽略，编辑页会自行加载 */
            }
          } else {
            message.error('分析失败，请检查任务详情。');
          }
        }
      } catch {
        // 轮询请求失败：停止轮询，避免无限重试
        stopPolling();
      }
    }, 2000);
  };

  if (!project) {
    return (
      <Card size="small">
        <Empty description="请先在「上传项目」页创建项目，再进行 AI 分析。" />
      </Card>
    );
  }

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <Card title="分析参数（用户意图）" size="small" extra={<Typography.Text type="secondary">项目：{project.title}</Typography.Text>}>
        <Form form={form} layout="vertical" initialValues={{ aspectRatio: '9:16', maxDuration: 60, addSubtitle: true, style: '快节奏口播' }}>
          <Space size="large" wrap align="start">
            <Form.Item name="aspectRatio" label="目标画幅" style={{ marginBottom: 0 }}>
              <Select
                style={{ width: 160 }}
                options={[
                  { value: '9:16', label: '9:16（竖屏）' },
                  { value: '16:9', label: '16:9（横屏）' },
                  { value: '1:1', label: '1:1（方形）' },
                  { value: '4:3', label: '4:3' },
                ]}
              />
            </Form.Item>
            <Form.Item name="maxDuration" label="目标时长（秒）" style={{ marginBottom: 0 }}>
              <InputNumber min={1} max={3600} step={10} style={{ width: 140 }} />
            </Form.Item>
            <Form.Item name="addSubtitle" label="生成字幕" valuePropName="checked" style={{ marginBottom: 0 }}>
              <Switch />
            </Form.Item>
            <Form.Item name="style" label="风格意图" style={{ marginBottom: 0 }}>
              <Input placeholder="自由文本，如：快节奏口播 / 温馨慢生活" style={{ width: 260 }} />
            </Form.Item>
            <Form.Item style={{ marginBottom: 0 }}>
              <Button type="primary" loading={starting || polling} onClick={handleAnalyze}>
                {polling ? '分析中…' : '开始分析'}
              </Button>
            </Form.Item>
          </Space>
        </Form>
      </Card>

      <Card title="分析任务进度" size="small">
        {task ? (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <Space>
              <Typography.Text type="secondary">任务 ID：</Typography.Text>
              <Typography.Text code>{task.taskId}</Typography.Text>
              <Tag color={STATUS_COLOR[task.status] ?? 'default'}>{task.status ?? 'PENDING'}</Tag>
            </Space>
            <Progress
              percent={Math.round(task.progress ?? 0)}
              status={task.status === 'FAILED' ? 'exception' : polling ? 'active' : 'normal'}
            />
            {task.status === 'SUCCESS' && onNavigate && (
              <Button type="primary" onClick={() => onNavigate('edit')}>
                去编辑方案 →
              </Button>
            )}
          </Space>
        ) : (
          <Typography.Text type="secondary">尚未发起分析任务。</Typography.Text>
        )}
      </Card>
    </Space>
  );
}
