package cn.sutone.cut.domain.analysis.model.valobj;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 一次分析的可信度标志（降级 / 质量）。
 *
 * <p>分析链路上有大量静默降级（探测失败→假元数据、ASR 失败→占位转写、VLM 失败→模拟理解），
 * 若不在界面上显式提示，一次彻底失败可能产出一份看起来完全正常的剪辑方案。
 * 这个值对象把「这份结果有多可信」这一领域事实带给上层。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class AnalysisFlags {

    private Long projectId;

    /** 本次分析是否使用了模拟 / 降级数据（对应 AnalysisReport.simulated）。 */
    private boolean simulated;

    /** 是否存在质量评审结果。 */
    private boolean qualityAvailable;

    /** 质量评审是否通过；无评审时为 null。 */
    private Boolean qualityPassed;

    /** 质量总分 0~1；无评审时为 null。 */
    private Double overallScore;
}
