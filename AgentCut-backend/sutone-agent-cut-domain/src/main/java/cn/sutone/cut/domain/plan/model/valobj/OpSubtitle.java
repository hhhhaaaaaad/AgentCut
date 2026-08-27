package cn.sutone.cut.domain.plan.model.valobj;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 字幕操作。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class OpSubtitle implements Operation {

    /** 字幕文本 */
    private String text;
    /** 显示起始时间（秒，相对片段） */
    private double start;
    /** 显示结束时间（秒，相对片段） */
    private double end;

    @Override
    public OperationType type() {
        return OperationType.SUBTITLE;
    }
}
