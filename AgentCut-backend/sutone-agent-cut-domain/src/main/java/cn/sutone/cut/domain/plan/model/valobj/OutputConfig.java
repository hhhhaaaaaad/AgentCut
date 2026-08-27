package cn.sutone.cut.domain.plan.model.valobj;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 输出配置。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class OutputConfig {

    private int width;
    private int height;
    private double fps;
    private String codec;
    private String bitrate;
}
