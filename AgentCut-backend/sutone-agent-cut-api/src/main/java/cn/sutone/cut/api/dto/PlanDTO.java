package cn.sutone.cut.api.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 方案响应 DTO（列表/概览用）。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class PlanDTO {

    private Long projectId;
    private int planVersion;
    private String title;
}
