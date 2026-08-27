package cn.sutone.cut.trigger.http;

import cn.sutone.cut.api.dto.ProjectDTO;
import cn.sutone.cut.app.service.ProjectService;
import cn.sutone.cut.domain.project.model.entity.ProjectEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 项目接口。
 */
@RestController
@RequestMapping("/api/v1")
public class ProjectController {

    private final ProjectService projectService;

    public ProjectController(ProjectService projectService) {
        this.projectService = projectService;
    }

    @PostMapping("/projects")
    public ProjectDTO createProject(@RequestBody ProjectDTO request) {
        ProjectEntity entity = projectService.createProject(request.getUserId(), request.getTitle());
        return toDTO(entity);
    }

    @GetMapping("/projects/{projectId}")
    public ProjectDTO queryProject(@PathVariable Long projectId) {
        return toDTO(projectService.queryProject(projectId));
    }

    private ProjectDTO toDTO(ProjectEntity e) {
        return ProjectDTO.builder()
                .projectId(e.getProjectId())
                .userId(e.getUserId())
                .title(e.getTitle())
                .status(e.getStatus())
                .build();
    }
}
