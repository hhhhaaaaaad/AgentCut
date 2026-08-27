package cn.sutone.cut.domain.plan.model.valobj;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 源时间区间（浮点秒）。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class TimeRange {

    /** 起始（秒） */
    private double start;
    /** 结束（秒） */
    private double end;
}
