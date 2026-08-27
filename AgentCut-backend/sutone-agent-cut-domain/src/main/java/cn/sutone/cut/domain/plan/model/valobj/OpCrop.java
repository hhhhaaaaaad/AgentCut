package cn.sutone.cut.domain.plan.model.valobj;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 画面裁切操作。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class OpCrop implements Operation {

    /** 裁切起点 X */
    private double x;
    /** 裁切起点 Y */
    private double y;
    /** 裁切宽度 */
    private double width;
    /** 裁切高度 */
    private double height;

    @Override
    public OperationType type() {
        return OperationType.CROP;
    }
}
