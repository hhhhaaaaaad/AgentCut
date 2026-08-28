package cn.sutone.cut.app.service;

import cn.sutone.cut.domain.project.adapter.repository.IProjectRepository;
import cn.sutone.cut.domain.project.model.entity.ProjectEntity;
import cn.sutone.cut.domain.project.service.ProjectDomainService;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 项目应用服务（创建/查询/列表/更新/删除）。
 */
@Service
public class ProjectService {

    private final ProjectDomainService projectDomainService;
    private final IProjectRepository projectRepository;

    public ProjectService(ProjectDomainService projectDomainService, IProjectRepository projectRepository) {
        this.projectDomainService = projectDomainService;
        this.projectRepository = projectRepository;
    }

    public ProjectEntity createProject(Long userId, String title) {
        return projectDomainService.createProject(userId, title);
    }

    public ProjectEntity queryProject(Long projectId) {
        return projectDomainService.query(projectId);
    }

    public List<ProjectEntity> listProjects(Long userId) {
        return projectRepository.queryByUserId(userId == null ? 0L : userId);
    }

    public ProjectEntity updateProject(Long projectId, String title, String status) {
        ProjectEntity existing = projectRepository.queryById(projectId);
        if (existing == null) {
            throw new IllegalArgumentException("项目不存在: " + projectId);
        }
        if (title != null && !title.isBlank()) {
            existing.setTitle(title);
        }
        if (status != null && !status.isBlank()) {
            existing.setStatus(status);
        }
        existing.setUpdatedAt(LocalDateTime.now());
        projectRepository.save(existing);
        return existing;
    }

    public void deleteProject(Long projectId) {
        projectRepository.delete(projectId);
    }
}
