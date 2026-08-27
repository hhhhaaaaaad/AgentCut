package cn.sutone.cut.domain.plan.model.valobj;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 源视频元信息（来自 ffprobe）。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class Source {

    private String assetId;
    private String url;
    private double duration;
    private double fps;
    private int width;
    private int height;
}
