package cn.sutone.cut.domain.plan.model.valobj;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 段间转场。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class Transition {

    private String from;
    private String to;
    private String type;
    private double duration;
}
