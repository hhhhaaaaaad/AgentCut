package cn.sutone.cut.domain.task.service;

import cn.sutone.cut.domain.task.adapter.repository.ITaskRepository;
import cn.sutone.cut.domain.task.model.entity.TaskEntity;
import cn.sutone.cut.domain.task.model.valobj.enums.TaskStatus;

/**
 * 任务领域服务：创建与状态流转。
 */
public class TaskDomainService {

    private final ITaskRepository taskRepository;

    public TaskDomainService(ITaskRepository taskRepository) {
        this.taskRepository = taskRepository;
    }

    public TaskEntity createPending(Long projectId, cn.sutone.cut.domain.task.model.valobj.enums.TaskType type, String payloadJson) {
        TaskEntity task = TaskEntity.builder()
                .projectId(projectId)
                .type(type)
                .status(TaskStatus.PENDING)
                .progress(0)
                .payloadJson(payloadJson)
                .build();
        taskRepository.save(task);
        return task;
    }

    public void start(Long taskId) {
        TaskEntity task = taskRepository.queryById(taskId);
        task.startRunning();
        taskRepository.update(task);
    }

    public void markSuccess(Long taskId, String resultJson) {
        TaskEntity task = taskRepository.queryById(taskId);
        task.markSuccess(resultJson);
        taskRepository.update(task);
    }

    public void markFailed(Long taskId, String errorMsg) {
        TaskEntity task = taskRepository.queryById(taskId);
        task.markFailed(errorMsg);
        taskRepository.update(task);
    }
}
