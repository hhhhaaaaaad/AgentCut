package cn.sutone.cut.api.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 任务响应 DTO。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class TaskDTO {

    private Long taskId;
    private String type;
    private String status;
    private int progress;
    private String resultJson;
}
