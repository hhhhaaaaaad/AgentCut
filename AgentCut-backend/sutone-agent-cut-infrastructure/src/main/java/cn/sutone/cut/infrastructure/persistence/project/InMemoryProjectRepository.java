package cn.sutone.cut.infrastructure.persistence.project;

import cn.sutone.cut.domain.project.adapter.repository.IProjectRepository;
import cn.sutone.cut.domain.project.model.entity.ProjectEntity;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

/**
 * 项目仓储 MVP 内存实现。后续替换为 MyBatis Mapper。
 */
@Repository
public class InMemoryProjectRepository implements IProjectRepository {

    private final Map<Long, ProjectEntity> store = new ConcurrentHashMap<>();
    private final AtomicLong idGen = new AtomicLong(1);

    @Override
    public void save(ProjectEntity project) {
        if (project.getProjectId() == null) {
            project.setProjectId(idGen.getAndIncrement());
        }
        store.put(project.getProjectId(), project);
    }

    @Override
    public ProjectEntity queryById(Long projectId) {
        return store.get(projectId);
    }

    @Override
    public List<ProjectEntity> queryByUserId(Long userId) {
        return store.values().stream().filter(p -> userId.equals(p.getUserId())).toList();
    }
}
