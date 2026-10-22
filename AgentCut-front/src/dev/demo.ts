import { useProjectStore } from '../stores/projectStore';

/** Explicit development-only fixture; never sends analysis or render requests. */
export function initializeDemo() {
  if (!import.meta.env.DEV || new URLSearchParams(window.location.search).get('demo') !== '1') return;
  useProjectStore.setState({
    demo: true,
    project: { projectId: 'P-2026-041', title: '旅行 Vlog 剪辑', status: 'DRAFT' },
    asset: { assetId: 'source-demo', projectId: 'P-2026-041', type: 'SOURCE', ossUrl: '', fileName: 'xunmeng.mp4', size: 68.4 * 1024 * 1024, duration: 60, width: 1920, height: 1080, fps: 30 },
    task: { taskId: 'A-1042', type: 'ANALYZE', status: 'NEEDS_REVIEW', progress: 100 },
    analysisFlags: { projectId: 41, simulated: true, qualityAvailable: true, qualityPassed: false, overallScore: .72 },
    plan: {
      schemaVersion: '1.0', planVersion: 3, projectId: 'P-2026-041',
      source: { assetId: 'source-demo', url: 'https://example.invalid/xunmeng.mp4', duration: 60, width: 1920, height: 1080, fps: 30 },
      global: { output: { width: 1080, height: 1920, fps: 30 }, subtitleStyle: { fontSize: 48, color: '#FFFFFF', position: 'bottom' } },
      timeline: [
        { id: 'seg_001', keep: true, sourceRange: { start: 0, end: 12.5 }, operations: [] },
        { id: 'seg_002', keep: true, sourceRange: { start: 12.5, end: 28.4 }, operations: [{ type: 'subtitle', text: '在山间，重新找到节奏', start: 0, end: 13.25 }, { type: 'speed', rate: 1.2 }] },
        { id: 'seg_003', keep: false, sourceRange: { start: 28.4, end: 37 }, operations: [] },
        { id: 'seg_004', keep: true, sourceRange: { start: 37, end: 60 }, operations: [] },
      ],
    },
    renderResult: { outputPath: '/render/output/P-2026-041-v3.mp4', duration: 58, size: 34.2 * 1024 * 1024 },
    renderedPlanVersion: 3,
    planVersions: ['1', '2', '3'],
  });
  useProjectStore.setState({ renderedPlan: structuredClone(useProjectStore.getState().plan) });
}
