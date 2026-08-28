package cn.sutone.cut.infrastructure.persistence.task;

import cn.sutone.cut.domain.task.adapter.repository.ITaskRepository;
import cn.sutone.cut.domain.task.model.entity.TaskEntity;
import cn.sutone.cut.infrastructure.persistence.mapper.TaskMapper;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Repository;

import java.util.List;

/**
 * 任务仓储 MyBatis 实现（mysql profile）。
 */
@Repository
@Profile("mysql")
public class MybatisTaskRepository implements ITaskRepository {

    private final TaskMapper taskMapper;

    public MybatisTaskRepository(TaskMapper taskMapper) {
        this.taskMapper = taskMapper;
    }

    @Override
    public void save(TaskEntity task) {
        taskMapper.insert(task);
    }

    @Override
    public TaskEntity queryById(Long taskId) {
        return taskMapper.selectById(taskId);
    }

    @Override
    public void update(TaskEntity task) {
        taskMapper.update(task);
    }

    @Override
    public List<TaskEntity> queryLatestByProjectId(Long projectId, int limit) {
        return taskMapper.selectLatestByProjectId(projectId, limit);
    }
}
