package cn.sutone.cut.trigger.http;

import cn.sutone.cut.api.dto.ProjectDTO;
import cn.sutone.cut.app.service.ProjectService;
import cn.sutone.cut.domain.project.model.entity.ProjectEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 项目接口（CRUD）。
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

    @GetMapping("/projects")
    public List<ProjectDTO> listProjects(@RequestParam(required = false) Long userId) {
        return projectService.listProjects(userId).stream().map(this::toDTO).toList();
    }

    @GetMapping("/projects/{projectId}")
    public ProjectDTO queryProject(@PathVariable Long projectId) {
        return toDTO(projectService.queryProject(projectId));
    }

    @PutMapping("/projects/{projectId}")
    public ProjectDTO updateProject(@PathVariable Long projectId, @RequestBody ProjectDTO request) {
        ProjectEntity entity = projectService.updateProject(projectId, request.getTitle(), request.getStatus());
        return toDTO(entity);
    }

    @DeleteMapping("/projects/{projectId}")
    public void deleteProject(@PathVariable Long projectId) {
        projectService.deleteProject(projectId);
    }

    private ProjectDTO toDTO(ProjectEntity e) {
        if (e == null) {
            return null;
        }
        return ProjectDTO.builder()
                .projectId(e.getProjectId())
                .userId(e.getUserId())
                .title(e.getTitle())
                .status(e.getStatus())
                .build();
    }
}
