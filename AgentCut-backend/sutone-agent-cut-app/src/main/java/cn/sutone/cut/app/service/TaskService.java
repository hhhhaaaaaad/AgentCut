package cn.sutone.cut.app.service;

import cn.sutone.cut.domain.task.adapter.repository.ITaskRepository;
import cn.sutone.cut.domain.task.model.entity.TaskEntity;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 任务应用服务（对外统一入口）。
 */
@Service
public class TaskService {

    private final ITaskRepository taskRepository;
    private final AnalyzeTaskService analyzeTaskService;
    private final RenderTaskService renderTaskService;

    public TaskService(ITaskRepository taskRepository, AnalyzeTaskService analyzeTaskService,
                       RenderTaskService renderTaskService) {
        this.taskRepository = taskRepository;
        this.analyzeTaskService = analyzeTaskService;
        this.renderTaskService = renderTaskService;
    }

    public Long analyze(Long projectId, String targetJson) {
        return analyzeTaskService.analyze(projectId, targetJson);
    }

    public Long render(Long projectId) {
        renderTaskService.render(projectId);
        return 0L;
    }

    public TaskEntity query(Long taskId) {
        return taskRepository.queryById(taskId);
    }

    public List<TaskEntity> listByProject(Long projectId) {
        return taskRepository.queryLatestByProjectId(projectId, 100);
    }
}
