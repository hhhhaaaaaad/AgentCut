package cn.sutone.cut.infrastructure.client;

import cn.sutone.cut.domain.adapter.port.IVideoAnalysisClient;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;

/**
 * Python 分析服务客户端（HTTP 调用 AgentCut-ai 的 /analyze）。
 *
 * <p>使用 JDK 内置 HttpClient + Jackson 序列化（正确处理 Windows 路径反斜杠等转义）。</p>
 */
@Component
public class PythonClient implements IVideoAnalysisClient {

    private final HttpClient httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(10))
            .build();

    private final ObjectMapper objectMapper;

    @Value("${agentcut.python.base-url:http://127.0.0.1:8000}")
    private String baseUrl;

    public PythonClient(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    @Override
    public String submitAnalyze(String videoUrl, String callbackUrl, String targetJson) {
        try {
            ObjectNode body = objectMapper.createObjectNode();
            body.put("videoUrl", videoUrl);
            body.put("callbackUrl", callbackUrl);
            body.set("target", objectMapper.readTree(targetJson));
            return post("/analyze", objectMapper.writeValueAsString(body));
        } catch (Exception e) {
            throw new IllegalStateException("构造分析请求失败: " + e.getMessage(), e);
        }
    }

    @Override
    public String queryStatus(String jobId) {
        return get("/analyze/" + jobId + "/status");
    }

    private String post(String path, String body) {
        try {
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(baseUrl + path))
                    .header("Content-Type", "application/json")
                    .timeout(Duration.ofSeconds(30))
                    .POST(HttpRequest.BodyPublishers.ofString(body))
                    .build();
            HttpResponse<String> resp = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            return resp.body();
        } catch (Exception e) {
            throw new IllegalStateException("调用 Python 分析服务失败: " + path, e);
        }
    }

    private String get(String path) {
        try {
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(baseUrl + path))
                    .timeout(Duration.ofSeconds(30))
                    .GET()
                    .build();
            HttpResponse<String> resp = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            return resp.body();
        } catch (Exception e) {
            throw new IllegalStateException("调用 Python 分析服务失败: " + path, e);
        }
    }
}
