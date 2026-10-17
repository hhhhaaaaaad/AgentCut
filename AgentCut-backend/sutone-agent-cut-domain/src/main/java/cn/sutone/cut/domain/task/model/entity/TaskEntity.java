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
    /** 当前步骤描述（如「语音转写 3/8」），供前端展示 */
    private String step;
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
        // 置 RUNNING 时立即打一次心跳：否则 heartbeatAt 为 null 的任务会被看门狗瞬间判为超时
        this.heartbeatAt = LocalDateTime.now();
        this.updatedAt = LocalDateTime.now();
    }

    /** 更新进度与当前步骤，并刷新心跳（心跳是看门狗判活依据）。 */
    public boolean updateProgress(int progress, String step) {
        if (this.status == TaskStatus.SUCCESS
                || this.status == TaskStatus.NEEDS_REVIEW
                || this.status == TaskStatus.FAILED) {
            return false;
        }
        int nextProgress = Math.max(0, Math.min(100, progress));
        if (nextProgress < this.progress) {
            return false;
        }
        this.status = TaskStatus.RUNNING;
        this.progress = nextProgress;
        this.step = step;
        this.heartbeatAt = LocalDateTime.now();
        this.updatedAt = LocalDateTime.now();
        return true;
    }

    public void markSuccess(String resultJson) {
        this.status = TaskStatus.SUCCESS;
        this.progress = 100;
        this.resultJson = resultJson;
        this.updatedAt = LocalDateTime.now();
    }

    public void markNeedsReview(String resultJson, String reason) {
        this.status = TaskStatus.NEEDS_REVIEW;
        this.progress = 100;
        this.resultJson = resultJson;
        this.errorMsg = reason;
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
