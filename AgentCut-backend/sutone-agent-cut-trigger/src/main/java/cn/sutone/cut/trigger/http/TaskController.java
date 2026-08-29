package cn.sutone.cut.trigger.http;

import cn.sutone.cut.api.dto.AnalyzeRequestDTO;
import cn.sutone.cut.api.dto.TaskDTO;
import cn.sutone.cut.app.service.AnalyzeTaskService;
import cn.sutone.cut.app.service.TaskService;
import cn.sutone.cut.domain.task.model.entity.TaskEntity;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.fasterxml.jackson.databind.JsonNode;

import java.util.List;

/**
 * 任务接口（分析 / 查询 / 列表 / 回调 / 渲染结果）。
 */
@RestController
@RequestMapping("/api/v1")
public class TaskController {

    private final TaskService taskService;
    private final AnalyzeTaskService analyzeTaskService;
    private final ObjectMapper objectMapper;

    public TaskController(TaskService taskService, AnalyzeTaskService analyzeTaskService, ObjectMapper objectMapper) {
        this.taskService = taskService;
        this.analyzeTaskService = analyzeTaskService;
        this.objectMapper = objectMapper;
    }

    /** 发起分析（半自动：分析完成后进入可编辑阶段，不自动渲染） */
    @PostMapping("/projects/{projectId}/analyze")
    public TaskDTO analyze(@PathVariable Long projectId, @RequestBody AnalyzeRequestDTO request) throws Exception {
        String targetJson = objectMapper.writeValueAsString(request);
        Long taskId = taskService.analyze(projectId, targetJson);
        return TaskDTO.builder().taskId(taskId).status("PENDING").progress(0).build();
    }

    @GetMapping("/tasks/{taskId}")
    public TaskDTO queryTask(@PathVariable Long taskId) {
        return toDTO(taskService.query(taskId));
    }

    @GetMapping("/projects/{projectId}/tasks")
    public List<TaskDTO> listTasks(@PathVariable Long projectId) {
        return taskService.listByProject(projectId).stream().map(this::toDTO).toList();
    }

    /** Python 分析完成回调：存报告 + 方案，标记任务成功 */
    @PostMapping("/analyze/callback")
    public void analyzeCallback(@RequestParam Long taskId, @RequestBody JsonNode body) {
        JsonNode result = body.get("result");
        String reportJson = result != null && result.has("analysis") ? result.get("analysis").toString() : "{}";
        String planJson = result != null && result.has("plan") ? result.get("plan").toString() : "{}";
        // quality 为 JSON null（SIMULATE 下）时落 null，避免把 "null" 字符串写库
        JsonNode quality = result != null ? result.get("quality") : null;
        String qualityJson = (quality != null && !quality.isNull()) ? quality.toString() : null;
        analyzeTaskService.handleCallback(taskId, reportJson, planJson, qualityJson);
    }

    /** 查询渲染结果（成片 outputPath） */
    @GetMapping("/render/{taskId}/result")
    public Object renderResult(@PathVariable Long taskId) throws Exception {
        TaskEntity t = taskService.query(taskId);
        if (t == null || t.getResultJson() == null) {
            return null;
        }
        return objectMapper.readTree(t.getResultJson());
    }

    private TaskDTO toDTO(TaskEntity t) {
        if (t == null) {
            return null;
        }
        return TaskDTO.builder()
                .taskId(t.getTaskId())
                .type(t.getType() != null ? t.getType().name() : null)
                .status(t.getStatus() != null ? t.getStatus().name() : null)
                .progress(t.getProgress())
                .resultJson(t.getResultJson())
                .build();
    }
}
