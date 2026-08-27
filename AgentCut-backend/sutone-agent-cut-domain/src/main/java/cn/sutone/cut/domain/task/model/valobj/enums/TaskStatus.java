package cn.sutone.cut.domain.task.model.valobj.enums;

/**
 * 任务状态机：PENDING → RUNNING → SUCCESS / RETRYING / FAILED。
 */
public enum TaskStatus {

    PENDING, RUNNING, SUCCESS, FAILED, RETRYING
}
