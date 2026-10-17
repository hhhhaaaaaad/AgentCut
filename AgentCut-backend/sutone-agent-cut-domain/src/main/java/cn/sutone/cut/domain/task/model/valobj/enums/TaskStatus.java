package cn.sutone.cut.domain.task.model.valobj.enums;

/**
 * 任务状态机：PENDING → RUNNING → SUCCESS / NEEDS_REVIEW / RETRYING / FAILED。
 */
public enum TaskStatus {

    PENDING, RUNNING, SUCCESS, NEEDS_REVIEW, FAILED, RETRYING
}
