package cn.sutone.cut.domain.plan.model.valobj;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 变速操作。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class OpSpeed implements Operation {

    /** 速率（>0，1.0 为原速，1.5 为 1.5 倍速） */
    private double rate;

    @Override
    public OperationType type() {
        return OperationType.SPEED;
    }
}
