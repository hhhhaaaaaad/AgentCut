package cn.sutone.cut.trigger.http;

import cn.sutone.cut.app.service.TaskService;
import cn.sutone.cut.domain.task.model.entity.TaskEntity;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.core.io.FileSystemResource;
import org.springframework.core.io.Resource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.nio.file.Files;
import java.nio.file.Path;

/**
 * 渲染成片接口（结果查询 / 流式下载）。
 */
@RestController
@RequestMapping("/api/v1")
public class RenderController {

    private final TaskService taskService;
    private final ObjectMapper objectMapper;

    public RenderController(TaskService taskService, ObjectMapper objectMapper) {
        this.taskService = taskService;
        this.objectMapper = objectMapper;
    }

    /**
     * 下载成片文件：从 RENDER 任务的 resultJson 里取 outputPath，以流返回。
     */
    @GetMapping("/render/{taskId}/download")
    public ResponseEntity<Resource> download(@PathVariable Long taskId) throws Exception {
        TaskEntity task = taskService.query(taskId);
        if (task == null) {
            throw new IllegalArgumentException("任务不存在: " + taskId);
        }
        String outputPath = resolveOutputPath(task);
        if (outputPath == null || outputPath.isBlank()) {
            throw new IllegalArgumentException("任务无成片结果: " + taskId);
        }

        Path file = Path.of(outputPath).toAbsolutePath().normalize();
        if (!Files.exists(file) || !Files.isRegularFile(file)) {
            throw new IllegalStateException("成片文件不存在: " + file);
        }

        Resource resource = new FileSystemResource(file);
        String fileName = file.getFileName() != null ? file.getFileName().toString() : "output.mp4";
        return ResponseEntity.ok()
                .header(HttpHeaders.CONTENT_DISPOSITION,
                        "attachment; filename=\"" + fileName + "\"")
                .contentType(MediaType.APPLICATION_OCTET_STREAM)
                .contentLength(Files.size(file))
                .body(resource);
    }

    /**
     * 从 resultJson 解析出成片 outputPath。
     */
    private String resolveOutputPath(TaskEntity task) {
        if (task.getResultJson() == null || task.getResultJson().isBlank()) {
            return null;
        }
        try {
            JsonNode node = objectMapper.readTree(task.getResultJson());
            JsonNode path = node.get("outputPath");
            return path == null || path.isNull() ? null : path.asText();
        } catch (Exception e) {
            return null;
        }
    }
}
