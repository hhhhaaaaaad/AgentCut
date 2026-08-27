import { useState } from 'react';
import { App as AntApp, ConfigProvider, Layout, Menu, Tag, Typography } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import UploadPage from './pages/UploadPage';
import AnalyzePage from './pages/AnalyzePage';
import EditPage from './pages/EditPage';
import PreviewPage from './pages/PreviewPage';
import { useProjectStore } from './stores/projectStore';
import type { PageKey } from './types/nav';

const { Header, Sider, Content } = Layout;

const MENU_ITEMS: { key: PageKey; label: string }[] = [
  { key: 'upload', label: '上传项目' },
  { key: 'analyze', label: 'AI 分析' },
  { key: 'edit', label: '方案编辑' },
  { key: 'preview', label: '预览导出' },
];

/**
 * AgentCut 前端根组件：
 * AntD Layout + Menu 导航，4 个页面用 state 切换（不强制 react-router）。
 */
export default function App() {
  const [activeKey, setActiveKey] = useState<PageKey>('upload');
  const project = useProjectStore((s) => s.project);

  const renderPage = () => {
    switch (activeKey) {
      case 'upload':
        return <UploadPage />;
      case 'analyze':
        return <AnalyzePage onNavigate={setActiveKey} />;
      case 'edit':
        return <EditPage onNavigate={setActiveKey} />;
      case 'preview':
        return <PreviewPage onNavigate={setActiveKey} />;
    }
  };

  return (
    <ConfigProvider locale={zhCN}>
      <AntApp>
        <Layout style={{ minHeight: '100vh' }}>
          <Sider width={220} theme="dark">
            <div
              style={{
                height: 56,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#fff',
                fontSize: 18,
                fontWeight: 600,
                letterSpacing: 1,
              }}
            >
              AgentCut
            </div>
            <Menu
              theme="dark"
              mode="inline"
              selectedKeys={[activeKey]}
              items={MENU_ITEMS}
              onClick={({ key }) => setActiveKey(key as PageKey)}
            />
          </Sider>
          <Layout>
            <Header
              style={{
                background: '#fff',
                padding: '0 24px',
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                borderBottom: '1px solid #f0f0f0',
              }}
            >
              <Typography.Title level={4} style={{ margin: 0 }}>
                视频智能剪辑平台
              </Typography.Title>
              {project ? (
                <Tag color="blue">当前项目：{project.title}</Tag>
              ) : (
                <Typography.Text type="secondary">尚未创建项目</Typography.Text>
              )}
            </Header>
            <Content style={{ margin: 16, padding: 24, background: '#fff', borderRadius: 8 }}>
              {renderPage()}
            </Content>
          </Layout>
        </Layout>
      </AntApp>
    </ConfigProvider>
  );
}
