package cn.sutone.cut.app;

import cn.sutone.cut.domain.adapter.port.VideoAnalysisSubmission;
import cn.sutone.cut.infrastructure.client.PythonClient;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertNull;

class PythonClientContractTest {

    private HttpServer server;
    private final AtomicReference<String> upgradeHeader = new AtomicReference<>();
    private final AtomicReference<String> requestBody = new AtomicReference<>();

    @AfterEach
    void tearDown() {
        if (server != null) {
            server.stop(0);
        }
    }

    @Test
    void acceptsOnly202WithJobId() throws Exception {
        PythonClient client = clientReturning(202, "{\"jobId\":\"job_1\",\"status\":\"pending\"}");

        VideoAnalysisSubmission submission = client.submitAnalyze("file:///video.mp4", "http://callback",
                "{\"aspectRatio\":\"16:9\"}");

        assertEquals("job_1", submission.jobId());
        assertEquals("pending", submission.status());
        assertNull(upgradeHeader.get(), "Uvicorn must receive a plain HTTP/1.1 request");
        var submitted = new ObjectMapper().readTree(requestBody.get());
        assertEquals("file:///video.mp4", submitted.path("videoUrl").asText());
        assertEquals("16:9", submitted.path("target").path("aspectRatio").asText());
    }

    @Test
    void rejectsNon202Response() throws Exception {
        PythonClient client = clientReturning(500, "{\"detail\":\"busy\"}");

        assertThrows(IllegalStateException.class,
                () -> client.submitAnalyze("file:///video.mp4", "http://callback", "{}"));
    }

    @Test
    void rejectsAcceptedResponseWithoutJobId() throws Exception {
        PythonClient client = clientReturning(202, "{\"status\":\"pending\"}");

        assertThrows(IllegalStateException.class,
                () -> client.submitAnalyze("file:///video.mp4", "http://callback", "{}"));
    }

    private PythonClient clientReturning(int status, String responseBody) throws Exception {
        server = HttpServer.create(new InetSocketAddress(0), 0);
        server.createContext("/analyze", exchange -> {
            upgradeHeader.set(exchange.getRequestHeaders().getFirst("Upgrade"));
            requestBody.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            byte[] body = responseBody.getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(status, body.length);
            try (var output = exchange.getResponseBody()) {
                output.write(body);
            }
        });
        server.start();

        PythonClient client = new PythonClient(new ObjectMapper());
        setField(client, "baseUrl", "http://127.0.0.1:" + server.getAddress().getPort());
        setField(client, "connectTimeoutSeconds", 2L);
        setField(client, "acceptTimeoutSeconds", 2L);
        return client;
    }

    private static void setField(Object target, String name, Object value) throws Exception {
        Field field = target.getClass().getDeclaredField(name);
        field.setAccessible(true);
        field.set(target, value);
    }
}
