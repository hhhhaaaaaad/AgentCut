package cn.sutone.cut.domain.plan.model.valobj;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 背景音乐配置。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class Bgm {

    private String url;
    private double volume;
    private boolean loop;
}
