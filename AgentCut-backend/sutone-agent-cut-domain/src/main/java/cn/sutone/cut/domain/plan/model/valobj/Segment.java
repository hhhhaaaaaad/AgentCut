package cn.sutone.cut.domain.plan.model.valobj;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.ArrayList;
import java.util.List;

/**
 * 时间线片段。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class Segment {

    /** 片段 ID */
    private String id;
    /** true=保留，false=剪掉 */
    private boolean keep;
    /** 源时间区间 */
    private TimeRange sourceRange;
    /** 段内操作（顺序执行） */
    @Builder.Default
    private List<Operation> operations = new ArrayList<>();
}
