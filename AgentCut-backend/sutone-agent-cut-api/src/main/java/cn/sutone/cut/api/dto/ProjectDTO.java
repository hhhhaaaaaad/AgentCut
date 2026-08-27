package cn.sutone.cut.api.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 项目响应 DTO。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class ProjectDTO {

    private Long projectId;
    private Long userId;
    private String title;
    private String status;
}
