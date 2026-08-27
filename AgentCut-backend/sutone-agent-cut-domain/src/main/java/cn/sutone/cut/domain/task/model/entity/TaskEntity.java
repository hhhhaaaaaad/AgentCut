package cn.sutone.cut.domain.task.model.entity;

import cn.sutone.cut.domain.task.model.valobj.enums.TaskStatus;
import cn.sutone.cut.domain.task.model.valobj.enums.TaskType;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

/**
 * 异步任务聚合根（ANALYZE / RENDER）。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class TaskEntity {

    private Long taskId;
    private Long projectId;
    private TaskType type;
    private TaskStatus status;
    /** 进度 0~100 */
    private int progress;
    /** 入参 JSON（如 videoUrl、planId） */
    private String payloadJson;
    /** 结果 JSON（如成片 URL） */
    private String resultJson;
    private String errorMsg;
    private LocalDateTime heartbeatAt;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;

    public void startRunning() {
        this.status = TaskStatus.RUNNING;
        this.updatedAt = LocalDateTime.now();
    }

    public void markSuccess(String resultJson) {
        this.status = TaskStatus.SUCCESS;
        this.progress = 100;
        this.resultJson = resultJson;
        this.updatedAt = LocalDateTime.now();
    }

    public void markFailed(String errorMsg) {
        this.status = TaskStatus.FAILED;
        this.errorMsg = errorMsg;
        this.updatedAt = LocalDateTime.now();
    }

    public void markRetrying(String errorMsg) {
        this.status = TaskStatus.RETRYING;
        this.errorMsg = errorMsg;
        this.updatedAt = LocalDateTime.now();
    }

    public void touchHeartbeat() {
        this.heartbeatAt = LocalDateTime.now();
    }
}
