package cn.sutone.cut.domain.project.service;

import cn.sutone.cut.domain.project.adapter.repository.IProjectRepository;
import cn.sutone.cut.domain.project.model.entity.ProjectEntity;

import java.time.LocalDateTime;

/**
 * 项目领域服务。
 */
public class ProjectDomainService {

    private final IProjectRepository projectRepository;

    public ProjectDomainService(IProjectRepository projectRepository) {
        this.projectRepository = projectRepository;
    }

    /**
     * 创建项目（单用户 MVP，userId 固定 0L）。
     */
    public ProjectEntity createProject(Long userId, String title) {
        ProjectEntity project = ProjectEntity.builder()
                .userId(userId == null ? 0L : userId)
                .title(title)
                .status("DRAFT")
                .createdAt(LocalDateTime.now())
                .updatedAt(LocalDateTime.now())
                .build();
        projectRepository.save(project);
        return project;
    }

    public ProjectEntity query(Long projectId) {
        return projectRepository.queryById(projectId);
    }
}
