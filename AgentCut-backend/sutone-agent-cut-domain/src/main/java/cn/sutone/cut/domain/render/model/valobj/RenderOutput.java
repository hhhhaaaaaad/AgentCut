package cn.sutone.cut.domain.render.model.valobj;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 渲染产物。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class RenderOutput {

    private String outputPath;
    private double duration;
    private long size;
}
