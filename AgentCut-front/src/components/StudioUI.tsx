import type { ReactNode } from 'react';
import { Button } from 'antd';
import type { PageKey } from '../types/nav';

export const PAGE_LABELS: Record<PageKey, string> = { upload: '上传项目', analyze: 'AI 分析', edit: '方案编辑', preview: '预览导出' };

export function Banner({ tone = 'info', title, description, trailing, onClick }: {
  tone?: 'info' | 'warning' | 'success' | 'error'; title: string; description: string; trailing?: string; onClick?: () => void;
}) {
  return <div className={`studio-banner banner-${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
    <span className="banner-symbol" aria-hidden>{tone === 'success' ? '✓' : tone === 'warning' || tone === 'error' ? '!' : '1'}</span>
    <div className="banner-copy"><strong>{title}</strong><p>{description}</p></div>
    {trailing && (onClick ? <button className="banner-link" onClick={onClick}>{trailing}</button> : <span className="banner-trailing">{trailing}</span>)}
  </div>;
}

export function PageHeading({ title, description, badge, actions }: { title: string; description: string; badge?: ReactNode; actions?: ReactNode }) {
  return <div className="page-heading"><div><div className="heading-title"><h1>{title}</h1>{badge}</div><p>{description}</p></div><div className="page-actions">{actions}</div></div>;
}

export function Panel({ title, extra, children, className = '' }: { title?: string; extra?: ReactNode; children: ReactNode; className?: string }) {
  return <section className={`studio-panel ${className}`}>{title && <div className="panel-heading"><h2>{title}</h2>{extra}</div>}{children}</section>;
}

export function StatusPill({ status }: { status: string }) {
  const tone = ['SUCCESS', 'APPLIED'].includes(status) ? 'success' : status === 'FAILED' ? 'error' : ['NEEDS_REVIEW', 'RETRYING'].includes(status) ? 'warning' : status === 'RUNNING' ? 'info' : 'neutral';
  return <span className={`status-pill pill-${tone}`}>{status}</span>;
}

export function EmptyState({ title, description, action, onAction }: { title: string; description: string; action?: string; onAction?: () => void }) {
  return <div className="studio-empty"><span className="empty-mark" aria-hidden>↗</span><h2>{title}</h2><p>{description}</p>{action && <Button type="primary" onClick={onAction}>{action}</Button>}</div>;
}

export function Landscape({ portrait = false }: { portrait?: boolean }) {
  return portrait ? <svg className="landscape" viewBox="0 0 270 475" preserveAspectRatio="none" aria-hidden>
    <defs><linearGradient id="portrait-sky" x1="0" y1="1" x2="0" y2="0"><stop stopColor="#567F99"/><stop offset=".6" stopColor="#1A3C51"/><stop offset="1" stopColor="#132A37"/></linearGradient></defs>
    <path fill="url(#portrait-sky)" d="M0 0h270v475H0z"/><circle cx="189.5" cy="102.5" r="36.5" fill="#E5B886AA"/>
    <path fill="#315A6D" d="M0 292l75-108 51 74 79-110 65 130 0 197-270 0z"/><path fill="#173D50" d="M0 364l72-77 60 55 64-85 74 81 0 137-270 0z"/>
    <path fill="#657981" d="M65 475l78-171 23 0 85 171z"/><path fill="#E6D7B1" d="M151 335l3 0-3 55-4 0z m-5 77l6 0 2 63-11 0z"/>
  </svg> : <svg className="landscape" viewBox="0 0 802 254" preserveAspectRatio="none" aria-hidden>
    <defs><linearGradient id="source-sky" x1="0" y1="1" x2="0" y2="0"><stop stopColor="#557C98"/><stop offset=".62" stopColor="#173349"/><stop offset="1" stopColor="#112632"/></linearGradient></defs>
    <path fill="url(#source-sky)" d="M0 0h802v254H0z"/><circle cx="668.5" cy="80.5" r="52.5" fill="#D6A97977"/>
    <path fill="#244D60" d="M0 206l122-96 143 84 153-116 192 128 192-76 0 124-802 0z"/><path fill="#153B4E" d="M0 248l120-58 118 36 132-68 140 72 145-60 147 59 0 25-802 0z"/>
    <path fill="#73848A" d="M330 254l107-73 30 0 100 73z"/><path fill="#E3D6B8" d="M446 198l2 0-37 56-6 0z"/>
  </svg>;
}
