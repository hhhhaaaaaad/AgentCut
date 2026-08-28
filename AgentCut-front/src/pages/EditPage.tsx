import { useEffect, useState, type ChangeEvent } from 'react';
import {
  Alert, App, Button, Card, Collapse, Divider, Empty, Form, Input, InputNumber, Popconfirm,
  Row, Col, Select, Space, Spin, Switch, Tag, Typography,
} from 'antd';
import { getPlan, savePlan } from '../api';
import { useProjectStore } from '../stores/projectStore';
import type { Bgm, Global, Operation, OperationType, OutputConfig, Plan, Segment, SubtitleStyle, TimeRange } from '../types/plan';
import { OPERATION_LABELS, createOperation } from '../types/plan';
import type { PageKey } from '../types/nav';

/** 操作类型下拉选项 */
const OPERATION_TYPE_OPTIONS = (Object.keys(OPERATION_LABELS) as OperationType[]).map((t) => ({
  value: t,
  label: OPERATION_LABELS[t],
}));

const SUBTITLE_POSITION_OPTIONS = [
  { value: 'top', label: '顶部' },
  { value: 'bottom', label: '底部' },
  { value: 'center', label: '居中' },
];

interface Props {
  onNavigate?: (page: PageKey) => void;
}

/**
 * 编辑页：方案编辑器。
 * 左侧结构化表单（global.output 宽高、timeline 片段 keep/start/end、段内 operations）
 * 右侧 JSON 编辑器（textarea，不引 Monaco）。
 * 读方案 → 改 → 展示双向同步；保存走 PUT /api/v1/plans/{id} 生成新版本。
 */
export default function EditPage({ onNavigate }: Props) {
  const { message } = App.useApp();
  const { project, plan, setPlan } = useProjectStore();

  const [loading, setLoading] = useState(false);
  const [jsonText, setJsonText] = useState('');
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  /** 每个片段待添加的操作类型（按片段 id 记忆） */
  const [pendingTypes, setPendingTypes] = useState<Record<string, OperationType>>({});

  // 进入页面即从后端拉取当前方案
  useEffect(() => {
    if (!project) return;
    setLoading(true);
    getPlan(project.projectId)
      .then((data) => {
        setPlan(data);
        setJsonText(JSON.stringify(data, null, 2));
      })
      .catch((err) => message.error(`加载方案失败：${err instanceof Error ? err.message : String(err)}`))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.projectId]);

  /** 结构化编辑 → 更新 plan 并同步 JSON 文本 */
  const commitPlan = (next: Plan) => {
    setPlan(next);
    setJsonText(JSON.stringify(next, null, 2));
  };

  /* ============ JSON 编辑 ============ */
  const onJsonChange = (e: ChangeEvent<HTMLTextAreaElement>) => {
    const text = e.target.value;
    setJsonText(text);
    try {
      const parsed = JSON.parse(text) as Plan;
      setPlan(parsed);
      setJsonError(null);
    } catch (err) {
      setJsonError(err instanceof Error ? err.message : 'JSON 格式错误');
    }
  };

  const formatJson = () => {
    if (plan) setJsonText(JSON.stringify(plan, null, 2));
  };

  /* ============ 全局设置 ============ */
  const updateGlobal = (patch: Partial<Global>) => {
    if (!plan) return;
    commitPlan({ ...plan, global: { ...plan.global, ...patch } });
  };
  const updateOutput = (patch: Partial<OutputConfig>) => {
    if (!plan) return;
    commitPlan({ ...plan, global: { ...plan.global, output: { ...plan.global.output, ...patch } } });
  };
  const updateSubtitleStyle = (patch: Partial<SubtitleStyle>) => {
    if (!plan) return;
    updateGlobal({ subtitleStyle: { ...plan.global.subtitleStyle, ...patch } });
  };
  /** 基于当前 bgm（可能不存在）构造新 bgm，供回调内安全调用 */
  const patchBgm = (patch: Partial<Bgm>) => {
    if (!plan) return;
    const base: Bgm = plan.global.bgm ?? { url: '', volume: 0.3, loop: true };
    updateGlobal({ bgm: { ...base, ...patch } });
  };

  /* ============ 时间线片段 ============ */
  const updateSegment = (index: number, patch: Partial<Segment>) => {
    if (!plan) return;
    const next = { ...plan, timeline: plan.timeline.map((s, i) => (i === index ? { ...s, ...patch } : s)) };
    commitPlan(next);
  };
  const updateSegmentRange = (index: number, field: keyof TimeRange, value: number) => {
    if (!plan) return;
    const seg = plan.timeline[index];
    updateSegment(index, { sourceRange: { ...seg.sourceRange, [field]: value } });
  };
  const updateOperationField = (segIndex: number, opIndex: number, field: string, value: number | string | boolean) => {
    if (!plan) return;
    const seg = plan.timeline[segIndex];
    const ops = seg.operations ?? [];
    const nextOp = { ...ops[opIndex], [field]: value } as Operation;
    updateSegment(segIndex, { operations: ops.map((o, i) => (i === opIndex ? nextOp : o)) });
  };
  const addOperation = (segIndex: number, type: OperationType) => {
    if (!plan) return;
    const seg = plan.timeline[segIndex];
    updateSegment(segIndex, { operations: [...(seg.operations ?? []), createOperation(type)] });
  };
  const removeOperation = (segIndex: number, opIndex: number) => {
    if (!plan) return;
    const seg = plan.timeline[segIndex];
    updateSegment(segIndex, { operations: (seg.operations ?? []).filter((_, i) => i !== opIndex) });
  };
  const addSegment = () => {
    if (!plan) return;
    const seg: Segment = {
      id: `seg_${String(plan.timeline.length + 1).padStart(3, '0')}`,
      keep: true,
      sourceRange: { start: 0, end: 0 },
      operations: [],
    };
    commitPlan({ ...plan, timeline: [...plan.timeline, seg] });
  };
  const removeSegment = (index: number) => {
    if (!plan) return;
    commitPlan({ ...plan, timeline: plan.timeline.filter((_, i) => i !== index) });
  };

  /* ============ 保存 ============ */
  const handleSave = async () => {
    if (!project || !plan) return;
    setSaving(true);
    try {
      await savePlan(project.projectId, plan);
      message.success('方案已保存');
    } catch (err) {
      message.error(`保存失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setSaving(false);
    }
  };

  if (!project) {
    return (
      <Card size="small">
        <Empty description="请先在「上传项目」页创建项目并完成分析，再编辑方案。" />
      </Card>
    );
  }

  return (
    <Spin spinning={loading}>
      {plan ? (
        <Space direction="vertical" style={{ width: '100%' }} size="large">
          <Card
            size="small"
            title={`剪辑方案 v${plan.planVersion}`}
            extra={
              <Space>
                <Button onClick={formatJson}>重新格式化</Button>
                <Button type="primary" loading={saving} onClick={handleSave}>
                  保存方案
                </Button>
              </Space>
            }
          >
            <Space wrap size="large">
              <Typography.Text type="secondary">Schema 版本：{plan.schemaVersion}</Typography.Text>
              <Typography.Text type="secondary">项目 ID：{plan.projectId}</Typography.Text>
              <Typography.Text type="secondary">
                源视频：{plan.source.url ? plan.source.url.split('/').pop() : '未配置'}（{plan.source.duration}s）
              </Typography.Text>
              <Typography.Text type="secondary">片段数：{plan.timeline.length}</Typography.Text>
            </Space>
          </Card>

          <Row gutter={16}>
            <Col span={12}>
              <Space direction="vertical" style={{ width: '100%' }} size="middle">
                {/* 全局设置 */}
                <Card title="全局设置（Global）" size="small">
                  <Typography.Text strong>输出配置（Output）</Typography.Text>
                  <Row gutter={12} style={{ marginTop: 8 }}>
                    <Col span={8}>
                      <Form.Item label="宽" style={{ marginBottom: 8 }}>
                        <InputNumber min={1} style={{ width: '100%' }} value={plan.global.output.width}
                          onChange={(v) => updateOutput({ width: v ?? 1080 })} />
                      </Form.Item>
                    </Col>
                    <Col span={8}>
                      <Form.Item label="高" style={{ marginBottom: 8 }}>
                        <InputNumber min={1} style={{ width: '100%' }} value={plan.global.output.height}
                          onChange={(v) => updateOutput({ height: v ?? 1920 })} />
                      </Form.Item>
                    </Col>
                    <Col span={8}>
                      <Form.Item label="帧率" style={{ marginBottom: 8 }}>
                        <InputNumber min={1} style={{ width: '100%' }} value={plan.global.output.fps}
                          onChange={(v) => updateOutput({ fps: v ?? 30 })} />
                      </Form.Item>
                    </Col>
                  </Row>

                  <Divider style={{ margin: '8px 0' }} />
                  {plan.global.bgm ? (
                    <>
                      <Typography.Text strong>背景音乐（Bgm）</Typography.Text>
                      <Row gutter={12} style={{ marginTop: 8 }}>
                        <Col span={14}>
                          <Form.Item label="URL" style={{ marginBottom: 8 }}>
                            <Input value={plan.global.bgm.url}
                              onChange={(e) => patchBgm({ url: e.target.value })} />
                          </Form.Item>
                        </Col>
                        <Col span={5}>
                          <Form.Item label="音量" style={{ marginBottom: 8 }}>
                            <InputNumber min={0} max={1} step={0.1} style={{ width: '100%' }} value={plan.global.bgm.volume}
                              onChange={(v) => patchBgm({ volume: v ?? 0.3 })} />
                          </Form.Item>
                        </Col>
                        <Col span={5}>
                          <Form.Item label="循环" style={{ marginBottom: 8 }}>
                            <Switch checked={plan.global.bgm.loop} style={{ marginTop: 4 }}
                              onChange={(v) => patchBgm({ loop: v })} />
                          </Form.Item>
                        </Col>
                      </Row>
                      <Button size="small" danger onClick={() => updateGlobal({ bgm: undefined })}>
                        移除背景音乐
                      </Button>
                    </>
                  ) : (
                    <Button size="small" onClick={() => updateGlobal({ bgm: { url: '', volume: 0.3, loop: true } })}>
                      添加背景音乐
                    </Button>
                  )}

                  <Divider style={{ margin: '8px 0' }} />
                  {plan.global.subtitleStyle ? (
                    <>
                      <Typography.Text strong>字幕样式（SubtitleStyle）</Typography.Text>
                      <Row gutter={12} style={{ marginTop: 8 }}>
                        <Col span={6}>
                          <Form.Item label="字号" style={{ marginBottom: 8 }}>
                            <InputNumber min={1} style={{ width: '100%' }} value={plan.global.subtitleStyle.fontSize}
                              onChange={(v) => updateSubtitleStyle({ fontSize: v ?? 48 })} />
                          </Form.Item>
                        </Col>
                        <Col span={9}>
                          <Form.Item label="颜色" style={{ marginBottom: 8 }}>
                            <Input value={plan.global.subtitleStyle.color}
                              onChange={(e) => updateSubtitleStyle({ color: e.target.value })} />
                          </Form.Item>
                        </Col>
                        <Col span={9}>
                          <Form.Item label="位置" style={{ marginBottom: 8 }}>
                            <Select style={{ width: '100%' }} value={plan.global.subtitleStyle.position}
                              options={SUBTITLE_POSITION_OPTIONS}
                              onChange={(v) => updateSubtitleStyle({ position: v })} />
                          </Form.Item>
                        </Col>
                      </Row>
                      <Button size="small" danger onClick={() => updateGlobal({ subtitleStyle: undefined })}>
                        移除字幕样式
                      </Button>
                    </>
                  ) : (
                    <Button size="small" onClick={() => updateGlobal({ subtitleStyle: { fontSize: 48, color: '#FFFFFF', position: 'bottom' } })}>
                      添加字幕样式
                    </Button>
                  )}
                </Card>

                {/* 时间线 */}
                <Card
                  title={`时间线（Timeline）`}
                  size="small"
                  extra={<Button size="small" onClick={addSegment}>新增片段</Button>}
                >
                  {plan.timeline.length === 0 ? (
                    <Empty description="暂无片段，点击「新增片段」添加" />
                  ) : (
                    <Collapse
                      size="small"
                      defaultActiveKey={[0]}
                      items={plan.timeline.map((seg, segIndex) => ({
                        key: segIndex,
                        label: (
                          <Space>
                            <Tag color={seg.keep ? 'green' : 'red'}>{seg.keep ? '保留' : '删除'}</Tag>
                            <Typography.Text code>{seg.id}</Typography.Text>
                            <Typography.Text type="secondary">
                              {seg.sourceRange.start.toFixed(1)}s → {seg.sourceRange.end.toFixed(1)}s
                            </Typography.Text>
                          </Space>
                        ),
                        children: (
                          <Space direction="vertical" style={{ width: '100%' }}>
                            <Space>
                              <span>保留此片段</span>
                              <Switch checked={seg.keep} onChange={(v) => updateSegment(segIndex, { keep: v })} />
                              <Popconfirm title="删除该片段？" onConfirm={() => removeSegment(segIndex)}>
                                <Button size="small" danger>删除片段</Button>
                              </Popconfirm>
                            </Space>
                            <Space>
                              <span>源区间</span>
                              <InputNumber addonBefore="开始" min={0} step={0.5} style={{ width: 130 }}
                                value={seg.sourceRange.start}
                                onChange={(v) => updateSegmentRange(segIndex, 'start', v ?? 0)} />
                              <InputNumber addonBefore="结束" min={0} step={0.5} style={{ width: 130 }}
                                value={seg.sourceRange.end}
                                onChange={(v) => updateSegmentRange(segIndex, 'end', v ?? 0)} />
                            </Space>
                            <Divider orientation="left" plain style={{ margin: '4px 0' }}>
                              段内操作（Operations）
                            </Divider>
                            {(seg.operations ?? []).map((op, opIndex) => (
                              <Card key={opIndex} size="small">
                                <Space direction="vertical" style={{ width: '100%' }}>
                                  <Space>
                                    <Tag color="blue">{OPERATION_LABELS[op.type]}</Tag>
                                    <Popconfirm title="删除该操作？" onConfirm={() => removeOperation(segIndex, opIndex)}>
                                      <Button size="small" danger>删除</Button>
                                    </Popconfirm>
                                  </Space>
                                  <OperationFields
                                    op={op}
                                    onChange={(field, value) => updateOperationField(segIndex, opIndex, field, value)}
                                  />
                                </Space>
                              </Card>
                            ))}
                            <Space>
                              <Select
                                style={{ width: 120 }}
                                value={pendingTypes[seg.id] ?? 'speed'}
                                options={OPERATION_TYPE_OPTIONS}
                                onChange={(t) => setPendingTypes((prev) => ({ ...prev, [seg.id]: t }))}
                              />
                              <Button size="small" onClick={() => addOperation(segIndex, pendingTypes[seg.id] ?? 'speed')}>
                                添加操作
                              </Button>
                            </Space>
                          </Space>
                        ),
                      }))}
                    />
                  )}
                </Card>
              </Space>
            </Col>

            <Col span={12}>
              <Card title="方案 JSON（可直接编辑）" size="small">
                <textarea
                  value={jsonText}
                  onChange={onJsonChange}
                  spellCheck={false}
                  style={{
                    width: '100%',
                    height: 560,
                    fontFamily: 'Consolas, Monaco, "Courier New", monospace',
                    fontSize: 12,
                    lineHeight: 1.6,
                    padding: 12,
                    border: jsonError ? '1px solid #ff4d4f' : '1px solid #d9d9d9',
                    borderRadius: 6,
                    resize: 'vertical',
                    background: '#fafafa',
                  }}
                />
                {jsonError ? (
                  <Alert style={{ marginTop: 8 }} type="error" showIcon message="JSON 有误，左侧表单暂不同步" description={jsonError} />
                ) : (
                  <Typography.Text type="secondary" style={{ marginTop: 8, display: 'block' }}>
                    JSON 合法：编辑将实时同步到左侧结构化表单。点击「保存方案」PUT 到后端生成新版本。
                  </Typography.Text>
                )}
              </Card>
            </Col>
          </Row>
        </Space>
      ) : (
        <Card size="small">
          <Empty description="暂无方案。请先在「AI 分析」页发起分析生成初稿方案。" />
          {onNavigate && (
            <div style={{ textAlign: 'center', marginTop: 8 }}>
              <Button onClick={() => onNavigate('analyze')}>去发起分析</Button>
            </div>
          )}
        </Card>
      )}
    </Spin>
  );
}

/** 按操作类型渲染可编辑参数（判别联合分发） */
function OperationFields({
  op,
  onChange,
}: {
  op: Operation;
  onChange: (field: string, value: number | string | boolean) => void;
}) {
  switch (op.type) {
    case 'speed':
      return (
        <Space wrap>
          <span>倍速</span>
          <InputNumber min={0.1} step={0.1} value={op.rate} onChange={(v) => onChange('rate', v ?? 1)} />
        </Space>
      );
    case 'crop':
      return (
        <Space wrap>
          <InputNumber addonBefore="x" min={0} value={op.x} onChange={(v) => onChange('x', v ?? 0)} />
          <InputNumber addonBefore="y" min={0} value={op.y} onChange={(v) => onChange('y', v ?? 0)} />
          <InputNumber addonBefore="宽" min={1} value={op.width} onChange={(v) => onChange('width', v ?? 0)} />
          <InputNumber addonBefore="高" min={1} value={op.height} onChange={(v) => onChange('height', v ?? 0)} />
        </Space>
      );
    case 'subtitle':
      return (
        <Space direction="vertical" style={{ width: '100%' }}>
          <Input addonBefore="文案" value={op.text} onChange={(e) => onChange('text', e.target.value)} />
          <Space>
            <InputNumber addonBefore="开始" min={0} value={op.start} onChange={(v) => onChange('start', v ?? 0)} />
            <InputNumber addonBefore="结束" min={0} value={op.end} onChange={(v) => onChange('end', v ?? 0)} />
          </Space>
        </Space>
      );
    case 'volume':
      return (
        <Space wrap>
          <span>音量</span>
          <InputNumber min={0} max={1} step={0.1} value={op.volume} onChange={(v) => onChange('volume', v ?? 1)} />
        </Space>
      );
    case 'mute':
      return <Typography.Text type="secondary">静音操作，无参数。</Typography.Text>;
  }
}
