package cn.sutone.cut.domain.task.adapter.repository;

import cn.sutone.cut.domain.task.model.entity.TaskEntity;
import cn.sutone.cut.domain.task.model.valobj.enums.TaskStatus;

import java.util.List;

/**
 * 任务仓储接口。
 */
public interface ITaskRepository {

    void save(TaskEntity task);

    TaskEntity queryById(Long taskId);

    void update(TaskEntity task);

    List<TaskEntity> queryLatestByProjectId(Long projectId, int limit);

    /** 按状态查询任务（看门狗扫描 RUNNING 任务用）。 */
    List<TaskEntity> queryByStatus(TaskStatus status);
}
