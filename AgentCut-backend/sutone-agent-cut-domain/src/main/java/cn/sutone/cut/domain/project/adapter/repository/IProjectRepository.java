package cn.sutone.cut.domain.project.adapter.repository;

import cn.sutone.cut.domain.project.model.entity.ProjectEntity;

import java.util.List;

/**
 * 项目仓储接口。
 */
public interface IProjectRepository {

    void save(ProjectEntity project);

    ProjectEntity queryById(Long projectId);

    List<ProjectEntity> queryByUserId(Long userId);
}
