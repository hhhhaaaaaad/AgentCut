package cn.sutone.cut.infrastructure.client;

import cn.sutone.cut.domain.adapter.port.IVideoAnalysisClient;
import cn.sutone.cut.domain.adapter.port.VideoAnalysisSubmission;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.HttpTimeoutException;
import java.time.Duration;

/**
 * Python 分析服务客户端（HTTP 调用 AgentCut-ai 的 /analyze）。
 *
 * <p>使用 JDK 内置 HttpClient + Jackson 序列化（正确处理 Windows 路径反斜杠等转义）。</p>
 */
@Component
public class PythonClient implements IVideoAnalysisClient {

    private final ObjectMapper objectMapper;

    @Value("${agentcut.python.base-url:http://127.0.0.1:8000}")
    private String baseUrl;
    @Value("${agentcut.python.connect-timeout-seconds:10}")
    private long connectTimeoutSeconds;
    @Value("${agentcut.python.accept-timeout-seconds:30}")
    private long acceptTimeoutSeconds;

    public PythonClient(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    @Override
    public VideoAnalysisSubmission submitAnalyze(String videoUrl, String callbackUrl, String targetJson) {
        try {
            ObjectNode body = objectMapper.createObjectNode();
            body.put("videoUrl", videoUrl);
            body.put("callbackUrl", callbackUrl);
            body.set("target", objectMapper.readTree(targetJson));
            HttpResponse<String> response = post("/analyze", objectMapper.writeValueAsString(body));
            if (response.statusCode() != 202) {
                throw new IllegalStateException(
                        "Python 分析服务未受理: HTTP " + response.statusCode());
            }
            JsonNode json = objectMapper.readTree(response.body());
            String jobId = json.path("jobId").asText("");
            String status = json.path("status").asText("");
            if (jobId.isBlank()) {
                throw new IllegalStateException("Python 受理响应缺少 jobId");
            }
            if (!"pending".equals(status) && !"running".equals(status)) {
                throw new IllegalStateException("Python 受理状态非法: " + status);
            }
            return new VideoAnalysisSubmission(jobId, status);
        } catch (Exception e) {
            if (e instanceof IllegalStateException illegalStateException) {
                throw illegalStateException;
            }
            throw new IllegalStateException("构造分析请求失败: " + e.getMessage(), e);
        }
    }

    private HttpResponse<String> post(String path, String body) {
        try {
            HttpClient httpClient = HttpClient.newBuilder()
                    // Uvicorn serves HTTP/1.1; avoid h2c upgrade requests losing the JSON body.
                    .version(HttpClient.Version.HTTP_1_1)
                    .connectTimeout(Duration.ofSeconds(connectTimeoutSeconds))
                    .build();
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(baseUrl + path))
                    .header("Content-Type", "application/json")
                    .timeout(Duration.ofSeconds(acceptTimeoutSeconds))
                    .POST(HttpRequest.BodyPublishers.ofString(body))
                    .build();
            HttpResponse<String> resp = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            return resp;
        } catch (HttpTimeoutException e) {
            throw new IllegalStateException("SUBMISSION_UNCERTAIN: Python 受理请求超时", e);
        } catch (Exception e) {
            throw new IllegalStateException("调用 Python 分析服务失败: " + path, e);
        }
    }
}
