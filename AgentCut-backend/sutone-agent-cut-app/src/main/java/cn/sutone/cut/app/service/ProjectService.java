package cn.sutone.cut.app.service;

import cn.sutone.cut.domain.project.model.entity.ProjectEntity;
import cn.sutone.cut.domain.project.service.ProjectDomainService;
import org.springframework.stereotype.Service;

/**
 * 项目应用服务。
 */
@Service
public class ProjectService {

    private final ProjectDomainService projectDomainService;

    public ProjectService(ProjectDomainService projectDomainService) {
        this.projectDomainService = projectDomainService;
    }

    public ProjectEntity createProject(Long userId, String title) {
        return projectDomainService.createProject(userId, title);
    }

    public ProjectEntity queryProject(Long projectId) {
        return projectDomainService.query(projectId);
    }
}
