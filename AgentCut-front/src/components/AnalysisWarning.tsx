import { Alert, Space } from 'antd';
import type { AnalysisFlags } from '../api';

/**
 * 分析可信度告警横幅。
 *
 * 背景：分析链路上有大量静默降级（探测失败→假元数据、ASR 失败→占位转写、VLM 失败→模拟理解），
 * 而界面上此前没有任何提示——一份建立在占位数据上的方案，看起来和真实方案完全一样。
 */
export default function AnalysisWarning({ flags }: { flags: AnalysisFlags | null }) {
  if (!flags) return null;

  const items = [];

  if (flags.simulated) {
    items.push(
      <Alert
        key="simulated"
        type="warning"
        showIcon
        message="本次分析使用了模拟 / 降级数据"
        description="未能取得真实的视频理解结果（模型或本地依赖不可用），方案中的场景描述与重要度仅供参考。"
      />,
    );
  }

  if (flags.qualityAvailable && flags.qualityPassed === false) {
    const score = flags.overallScore != null ? `（总分 ${flags.overallScore.toFixed(2)}）` : '';
    items.push(
      <Alert
        key="quality"
        type="warning"
        showIcon
        message={`质量评审未通过${score}`}
        description="方案可能存在时间轴缺口、节奏或变速处理等问题，建议在编辑页逐条核对后再导出。"
      />,
    );
  }

  if (items.length === 0) return null;

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="small">
      {items}
    </Space>
  );
}
