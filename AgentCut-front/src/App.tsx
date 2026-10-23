import { useEffect, useState } from 'react';
import { App as AntApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import UploadPage from './pages/UploadPage';
import AnalyzePage from './pages/AnalyzePage';
import EditPage from './pages/EditPage';
import PreviewPage from './pages/PreviewPage';
import { PAGE_LABELS } from './components/StudioUI';
import { useProjectStore } from './stores/projectStore';
import { savedPlanVersion } from './lib/plan';
import type { PageKey } from './types/nav';

const pages: PageKey[] = ['upload', 'analyze', 'edit', 'preview'];
const pageFromHash = (): PageKey => pages.includes(window.location.hash.slice(1) as PageKey) ? window.location.hash.slice(1) as PageKey : 'upload';

export default function App() {
  const [activePage, setActivePage] = useState<PageKey>(pageFromHash);
  const [menuOpen, setMenuOpen] = useState(false);
  const { project, task, asset, plan, planVersions, planDirty, renderResult, uploading, demo } = useProjectStore();
  useEffect(() => {
    const onHash = () => setActivePage(pageFromHash());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);
  const navigate = (page: PageKey) => {
    setActivePage(page);
    window.location.hash = page;
    setMenuOpen(false);
  };
  const projectStatus = uploading ? '源视频上传中' : planDirty ? '方案有未保存修改' : renderResult ? '成片已生成' : task?.status === 'NEEDS_REVIEW' ? '分析完成 · 待复核' : plan ? `方案 v${savedPlanVersion(plan, planVersions)} · 已保存` : task?.status === 'FAILED' ? '分析失败' : task && ['RUNNING', 'PENDING', 'RETRYING'].includes(task.status) ? '正在分析' : asset ? '源视频已上传' : '等待上传源视频';

  return <ConfigProvider locale={zhCN} theme={{ token: { colorPrimary: '#2E88D8', borderRadius: 7, fontFamily: 'Inter, "PingFang SC", "Microsoft YaHei", sans-serif', colorText: '#2B4353', colorBorder: '#D8E3EA', controlHeight: 40, fontSize: 13 }, components: { Button: { primaryShadow: 'none', defaultShadow: 'none', fontWeight: 600 }, Input: { activeShadow: '0 0 0 2px #2e88d815' } } }}>
    <AntApp><div className={`studio-app ${menuOpen ? 'menu-open' : ''}`}>
      {menuOpen && <button className="sidebar-backdrop" aria-label="收起导航" onClick={() => setMenuOpen(false)}/>}
      <aside className="studio-sidebar">
        <button className="studio-brand" onClick={() => navigate('upload')} aria-label="AgentCut 工作台首页"><span className="brand-mark">AC</span><span><strong>AgentCut</strong><small>CREATOR STUDIO</small></span></button>
        <div className="nav-group-label">工作流程</div>
        <nav aria-label="工作流程">{pages.map((page, index) => <button key={page} className={`studio-nav-item ${activePage === page ? 'active' : ''}`} aria-current={activePage === page ? 'page' : undefined} onClick={() => navigate(page)}><span className="nav-number">0{index + 1}</span><span>{PAGE_LABELS[page]}</span></button>)}</nav>
        <div className="sidebar-project"><small>当前项目</small><strong title={project?.title}>{project?.title || '尚未创建项目'}</strong><span><i/>{project ? projectStatus : '创建项目，开启剪辑'}</span></div>
      </aside>
      <div className="studio-main">
        <header className="studio-topbar"><div className="topbar-location"><button className="mobile-menu" aria-label="展开导航" aria-expanded={menuOpen} onClick={() => setMenuOpen(!menuOpen)}>☰</button><span>工作台</span><span className="breadcrumb-separator">/</span><span className="breadcrumb-project">{project?.title || '新建项目'}</span><span className="breadcrumb-separator">/</span><span>{PAGE_LABELS[activePage]}</span></div><div className="topbar-meta">{demo && <span className="demo-tag">界面示例</span>}<span className="project-id">{project ? `项目 #${project.projectId}` : 'CREATOR WORKSPACE'}</span><span className="avatar" aria-hidden>M</span></div></header>
        <main className="studio-content">
          {activePage === 'upload' && <UploadPage onNavigate={navigate}/>}
          {activePage === 'analyze' && <AnalyzePage onNavigate={navigate}/>}
          {activePage === 'edit' && <EditPage onNavigate={navigate}/>}
          {activePage === 'preview' && <PreviewPage onNavigate={navigate}/>}
        </main>
      </div>
    </div></AntApp>
  </ConfigProvider>;
}
