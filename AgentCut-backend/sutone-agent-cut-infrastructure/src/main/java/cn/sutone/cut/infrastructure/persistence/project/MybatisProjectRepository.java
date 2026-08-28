package cn.sutone.cut.infrastructure.persistence.project;

import cn.sutone.cut.domain.project.adapter.repository.IProjectRepository;
import cn.sutone.cut.domain.project.model.entity.ProjectEntity;
import cn.sutone.cut.infrastructure.persistence.mapper.ProjectMapper;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Repository;

import java.util.List;

/**
 * 项目仓储 MyBatis 实现（mysql profile）。
 */
@Repository
@Profile("mysql")
public class MybatisProjectRepository implements IProjectRepository {

    private final ProjectMapper projectMapper;

    public MybatisProjectRepository(ProjectMapper projectMapper) {
        this.projectMapper = projectMapper;
    }

    @Override
    public void save(ProjectEntity project) {
        if (project.getProjectId() == null) {
            projectMapper.insert(project);
        } else {
            projectMapper.update(project);
        }
    }

    @Override
    public ProjectEntity queryById(Long projectId) {
        return projectMapper.selectById(projectId);
    }

    @Override
    public List<ProjectEntity> queryByUserId(Long userId) {
        return projectMapper.selectByUserId(userId);
    }

    @Override
    public void delete(Long projectId) {
        projectMapper.delete(projectId);
    }
}
