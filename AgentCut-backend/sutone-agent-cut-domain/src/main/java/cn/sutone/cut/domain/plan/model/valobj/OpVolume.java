package cn.sutone.cut.domain.plan.model.valobj;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 音量操作（0~1）。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class OpVolume implements Operation {

    /** 音量（0~1） */
    private double volume;

    @Override
    public OperationType type() {
        return OperationType.VOLUME;
    }
}
