package cn.sutone.cut.domain.plan.model.valobj;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 字幕样式。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class SubtitleStyle {

    private int fontSize;
    private String color;
    private String position;
}
