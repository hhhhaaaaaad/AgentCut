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
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;

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

    /**
     * Python 回调入口，按 {@code event} 字段分流：
     * <ul>
     *   <li>{@code progress} —— 中间进度事件：只更新进度与步骤（含心跳），不落库方案</li>
     *   <li>completed + status=failed —— 只记录失败，不保存报告或方案</li>
     *   <li>completed + status=success —— 校验结果后保存报告和方案</li>
     * </ul>
     */
    @PostMapping("/analyze/callback")
    public void analyzeCallback(@RequestParam Long taskId, @RequestBody JsonNode body) {
        validateJobId(taskId, body);
        if ("progress".equals(body.path("event").asText())) {
            analyzeTaskService.updateProgress(
                    taskId,
                    body.path("progress").asInt(0),
                    body.path("step").asText(""));
            return;
        }

        String status = body.path("status").asText("");
        if ("failed".equals(status)) {
            JsonNode error = body.path("error");
            String errorCode = error.path("code").asText("");
            String errorMessage = error.path("message").asText(error.asText(""));
            analyzeTaskService.handleFailure(taskId, errorCode, errorMessage);
            return;
        }
        if (!status.isBlank() && !"success".equals(status)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "分析回调 status 非法: " + status);
        }

        JsonNode result = body.get("result");
        if (result == null || !result.has("analysis") || !result.has("plan")) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST,
                    "成功分析回调缺少 result.analysis 或 result.plan");
        }
        String reportJson = result.get("analysis").toString();
        String planJson = result.get("plan").toString();
        // quality 为 JSON null（SIMULATE 下）时落 null，避免把 "null" 字符串写库
        JsonNode quality = result != null ? result.get("quality") : null;
        String qualityJson = (quality != null && !quality.isNull()) ? quality.toString() : null;
        analyzeTaskService.handleCallback(taskId, reportJson, planJson, qualityJson);
    }

    /**
     * 回调携带 jobId 时校验其与 Java 任务受理记录一致。
     * 旧版回调缺少 jobId 时保留兼容，但新版回调不能串任务。
     */
    private void validateJobId(Long taskId, JsonNode body) {
        String callbackJobId = body.path("jobId").asText("");
        if (callbackJobId.isBlank()) {
            return;
        }
        TaskEntity task = taskService.query(taskId);
        if (task == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "任务不存在: " + taskId);
        }
        try {
            String expectedJobId = objectMapper.readTree(task.getPayloadJson())
                    .path("pythonJobId").asText("");
            if (!expectedJobId.isBlank() && !expectedJobId.equals(callbackJobId)) {
                throw new ResponseStatusException(
                        HttpStatus.BAD_REQUEST,
                        "Python jobId 与任务不匹配");
            }
        } catch (ResponseStatusException e) {
            throw e;
        } catch (Exception e) {
            throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR, "任务 payload 无法解析", e);
        }
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
                .step(t.getStep())
                .resultJson(t.getResultJson())
                .build();
    }
}
