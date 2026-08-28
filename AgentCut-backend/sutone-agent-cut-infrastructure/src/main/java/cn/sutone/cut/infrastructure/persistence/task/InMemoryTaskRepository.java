package cn.sutone.cut.infrastructure.persistence.task;

import cn.sutone.cut.domain.task.adapter.repository.ITaskRepository;
import cn.sutone.cut.domain.task.model.entity.TaskEntity;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

/**
 * 任务仓储 MVP 内存实现。后续替换为 MyBatis Mapper。
 */
@Repository
@Profile("!mysql")
public class InMemoryTaskRepository implements ITaskRepository {

    private final Map<Long, TaskEntity> store = new ConcurrentHashMap<>();
    private final AtomicLong idGen = new AtomicLong(1);

    @Override
    public void save(TaskEntity task) {
        if (task.getTaskId() == null) {
            task.setTaskId(idGen.getAndIncrement());
        }
        store.put(task.getTaskId(), task);
    }

    @Override
    public TaskEntity queryById(Long taskId) {
        return store.get(taskId);
    }

    @Override
    public void update(TaskEntity task) {
        store.put(task.getTaskId(), task);
    }

    @Override
    public List<TaskEntity> queryLatestByProjectId(Long projectId, int limit) {
        return store.values().stream()
                .filter(t -> projectId.equals(t.getProjectId()))
                .sorted((a, b) -> Long.compare(b.getTaskId(), a.getTaskId()))
                .limit(limit)
                .toList();
    }
}
