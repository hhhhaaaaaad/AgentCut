import { useState } from 'react';
import { App, Button, Card, Descriptions, Form, Input, Space, Typography, Upload, Tag } from 'antd';
import { createProject, uploadVideo, type Asset, type CreateProjectRequest } from '../api';
import { useProjectStore } from '../stores/projectStore';

/**
 * 上传页：创建项目 → 上传视频（分片上传占位）。
 */
export default function UploadPage() {
  const { message } = App.useApp();
  const { project, setProject } = useProjectStore();
  const [form] = Form.useForm<CreateProjectRequest>();
  const [creating, setCreating] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [asset, setAsset] = useState<Asset | null>(null);

  const handleCreate = async () => {
    const values = await form.validateFields();
    setCreating(true);
    try {
      const created = await createProject({
        title: values.title,
        userId: values.userId || undefined,
      });
      setProject(created);
      setAsset(null);
      message.success(`项目已创建：${created.title}`);
    } catch (err) {
      message.error(`创建项目失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setCreating(false);
    }
  };

  const handleUpload = async (file: File) => {
    if (!project) return;
    setUploading(true);
    try {
      const uploaded = await uploadVideo(project.projectId, file);
      setAsset(uploaded);
      message.success(`视频上传成功：${uploaded.fileName}（素材 #${uploaded.assetId}）`);
    } catch (err) {
      message.error(`上传失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setUploading(false);
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
                当前为整文件上传（multipart），分片上传 / 断点续传规划中
              </Typography.Text>
            }
          >
            <Upload.Dragger
              disabled={uploading}
              multiple={false}
              showUploadList={false}
              beforeUpload={(file) => {
                void handleUpload(file);
                return false;
              }}
            >
              <p style={{ fontSize: 16, marginTop: 24 }}>
                {uploading ? '上传中…' : '点击或将视频拖拽到此处上传'}
              </p>
              <p style={{ color: '#999' }}>选择视频文件后自动上传到后端，建立 SOURCE 素材。</p>
            </Upload.Dragger>
            {asset && (
              <Descriptions column={2} size="small" style={{ marginTop: 12 }}>
                <Descriptions.Item label="素材 ID">{asset.assetId}</Descriptions.Item>
                <Descriptions.Item label="类型">
                  <Tag color="green">{asset.type}</Tag>
                </Descriptions.Item>
                <Descriptions.Item label="文件名">{asset.fileName}</Descriptions.Item>
                <Descriptions.Item label="大小">{(asset.size / 1024 / 1024).toFixed(2)} MB</Descriptions.Item>
              </Descriptions>
            )}
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
