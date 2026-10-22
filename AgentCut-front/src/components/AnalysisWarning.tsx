import type { AnalysisFlags } from '../api';
import { Banner } from './StudioUI';

export default function AnalysisWarning({ flags, onDetails, needsReview = false }: { flags: AnalysisFlags | null; onDetails?: () => void; needsReview?: boolean }) {
  const failedQuality = flags?.qualityAvailable && flags.qualityPassed === false;
  if (!flags?.simulated && !failedQuality && !needsReview) return null;
  const title = failedQuality || needsReview ? '分析完成，方案需要人工复核' : '本次分析包含模拟 / 降级数据';
  const description = [flags?.simulated ? '结果包含模拟 / 降级数据' : '', failedQuality ? '质量评审未通过' : ''].filter(Boolean).join('，');
  return <Banner tone="warning" title={title} description={`${description ? `${description}。` : ''}请先核对源视频与片段时间，再保存方案。`} trailing={onDetails ? '查看可信度 →' : undefined} onClick={onDetails}/>;
}
