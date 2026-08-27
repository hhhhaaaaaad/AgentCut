package cn.sutone.cut.domain.project.model.entity;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

/**
 * 剪辑项目聚合根。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class ProjectEntity {

    private Long projectId;
    /** 单用户 MVP 固定为 0L，为多租户预留 */
    private Long userId;
    private String title;
    private Long sourceAssetId;
    private String status;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
