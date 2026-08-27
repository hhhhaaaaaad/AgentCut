import { useState } from 'react';
import { App, Button, Card, Descriptions, Form, Input, Space, Typography, Upload, Tag } from 'antd';
import { createProject, type CreateProjectRequest } from '../api';
import { useProjectStore } from '../stores/projectStore';

/**
 * 上传页：创建项目 → 上传视频（分片上传占位）。
 */
export default function UploadPage() {
  const { message } = App.useApp();
  const { project, setProject } = useProjectStore();
  const [form] = Form.useForm<CreateProjectRequest>();
  const [creating, setCreating] = useState(false);

  const handleCreate = async () => {
    const values = await form.validateFields();
    setCreating(true);
    try {
      const created = await createProject({
        title: values.title,
        userId: values.userId || undefined,
      });
      setProject(created);
      message.success(`项目已创建：${created.title}`);
    } catch (err) {
      message.error(`创建项目失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setCreating(false);
    }
  };

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <Card title="创建项目" size="small">
        <Form form={form} layout="inline" initialValues={{ title: '我的剪辑项目' }}>
          <Form.Item
            name="title"
            label="项目名称"
            rules={[{ required: true, message: '请输入项目名称' }]}
          >
            <Input placeholder="例如：旅行 Vlog 剪辑" style={{ width: 240 }} />
          </Form.Item>
          <Form.Item name="userId" label="用户 ID">
            <Input placeholder="留空使用默认用户" style={{ width: 160 }} />
          </Form.Item>
          <Form.Item>
            <Button type="primary" loading={creating} onClick={handleCreate}>
              创建项目
            </Button>
          </Form.Item>
        </Form>
      </Card>

      {project ? (
        <>
          <Card title="当前项目" size="small">
            <Descriptions column={3} size="small" bordered>
              <Descriptions.Item label="项目 ID">{project.projectId}</Descriptions.Item>
              <Descriptions.Item label="标题">{project.title}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color="blue">{project.status || 'DRAFT'}</Tag>
              </Descriptions.Item>
              {project.userId && (
                <Descriptions.Item label="用户 ID">{project.userId}</Descriptions.Item>
              )}
            </Descriptions>
          </Card>

          <Card
            title="上传源视频"
            size="small"
            extra={
              <Typography.Text type="warning">
                分片上传（断点续传 / 秒传）规划中，见后端 /projects/{'{id}'}/upload
              </Typography.Text>
            }
          >
            <Upload.Dragger disabled beforeUpload={() => false} multiple={false}>
              <p style={{ fontSize: 16, marginTop: 24 }}>点击或将视频拖拽到此处上传</p>
              <p style={{ color: '#999' }}>
                TODO：分片上传（sliced upload + progress）待实现；当前为占位，不发起真实请求。
              </p>
            </Upload.Dragger>
          </Card>
        </>
      ) : (
        <Card size="small">
          <Typography.Text type="secondary">
            请先创建项目，再上传源视频，进入「AI 分析」页发起分析。
          </Typography.Text>
        </Card>
      )}
    </Space>
  );
}
