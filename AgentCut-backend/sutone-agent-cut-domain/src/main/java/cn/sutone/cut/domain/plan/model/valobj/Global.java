package cn.sutone.cut.domain.plan.model.valobj;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 全局设置（输出/BGM/字幕样式）。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class Global {

    private OutputConfig output;
    private Bgm bgm;
    private SubtitleStyle subtitleStyle;
}
