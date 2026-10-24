package cn.sutone.cut.trigger.http;

import cn.sutone.cut.app.service.ScriptTaskService;
import com.fasterxml.jackson.databind.JsonNode;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Profile;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Map;

@RestController
@RequestMapping("/api/v1")
@Profile("local & !mysql")
@ConditionalOnProperty(name = "agentcut.script-tasks.enabled", havingValue = "true")
public class ScriptTaskController {
    private final ScriptTaskService tasks;
    public ScriptTaskController(ScriptTaskService tasks) { this.tasks = tasks; }

    @PostMapping("/projects/{projectId}/script-tasks")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public JsonNode create(@PathVariable Long projectId, HttpServletRequest request) throws IOException {
        return tasks.create(projectId, body(request, 64_000));
    }
    @GetMapping("/projects/{projectId}/script-tasks")
    public JsonNode list(@PathVariable Long projectId, @RequestParam(defaultValue = "0") int offset,
                         @RequestParam(defaultValue = "20") int limit) { return tasks.list(projectId, offset, limit); }
    @GetMapping("/script-tasks/{id}")
    public JsonNode query(@PathVariable String id) { return tasks.query(id); }
    @GetMapping("/script-tasks/{id}/script")
    public JsonNode script(@PathVariable String id) { return tasks.result(id, true); }
    @GetMapping("/script-tasks/{id}/result")
    public JsonNode result(@PathVariable String id) { return tasks.result(id, false); }
    @GetMapping("/script-tasks/{id}/evidence")
    public JsonNode evidence(@PathVariable String id) { return tasks.evidence(id); }
    @PostMapping("/script-tasks/{id}/reconcile")
    public JsonNode reconcile(@PathVariable String id) { return tasks.reconcile(id); }
    @PostMapping("/script-tasks/{id}/events")
    public Map<String, String> event(@PathVariable String id, @RequestHeader("X-AgentCut-Run-Token") String token,
                                    HttpServletRequest request) throws IOException {
        return Map.of("disposition", tasks.receive(id, token, body(request, 20_000_000)));
    }
    @ExceptionHandler(ScriptTaskService.Problem.class)
    public ResponseEntity<Map<String, String>> problem(ScriptTaskService.Problem error) {
        return ResponseEntity.status(error.status).body(Map.of("code", error.getMessage()));
    }
    private JsonNode body(HttpServletRequest request, int limit) throws IOException {
        byte[] bytes = request.getInputStream().readNBytes(limit + 1);
        if (bytes.length > limit) throw new ScriptTaskService.Problem(413, "REQUEST_TOO_LARGE");
        return tasks.read(new String(bytes, StandardCharsets.UTF_8));
    }
}
