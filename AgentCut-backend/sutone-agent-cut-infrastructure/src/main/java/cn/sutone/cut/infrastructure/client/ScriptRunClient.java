package cn.sutone.cut.infrastructure.client;

import cn.sutone.cut.domain.adapter.port.IScriptRunClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.io.ByteArrayOutputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.nio.ByteBuffer;
import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionStage;
import java.util.concurrent.Flow;
import java.util.concurrent.TimeUnit;

@Component
public class ScriptRunClient implements IScriptRunClient {
    private final String baseUrl;
    private final Duration timeout;
    private final HttpClient http;
    public ScriptRunClient(@Value("${agentcut.python.base-url:http://127.0.0.1:8000}") String baseUrl,
                           @Value("${agentcut.python.accept-timeout-seconds:30}") long timeout) {
        this.baseUrl = baseUrl.replaceAll("/+$", "");
        this.timeout = Duration.ofSeconds(timeout);
        this.http = HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(Duration.ofSeconds(5)).followRedirects(HttpClient.Redirect.NEVER).build();
    }
    public String submit(String snapshotJson) { return exchange("", snapshotJson, null); }
    public String status(String runId, String token) {
        if (!runId.matches("[A-Za-z0-9_-]+")) throw new IllegalArgumentException("invalid runId");
        return exchange("/" + runId, null, token);
    }
    private String exchange(String suffix, String body, String token) {
        try {
            var builder = HttpRequest.newBuilder(URI.create(baseUrl + "/v1/script-runs" + suffix)).timeout(timeout);
            if (token != null) builder.header("X-AgentCut-Run-Token", token);
            var request = body == null ? builder.GET().build() : builder.header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(body)).build();
            var future = http.sendAsync(request, info -> new LimitedBody());
            try {
                var response = future.get(timeout.toMillis(), TimeUnit.MILLISECONDS);
                // 4xx/503 are definite rejections; 5xx, redirects and malformed 202
                // may follow execution and must remain uncertain.
                if ((body == null && response.statusCode() != 200) || (body != null && response.statusCode() != 202)) {
                    throw new SubmissionException(body == null || !(response.statusCode() >= 400
                            && response.statusCode() < 500 || response.statusCode() == 503));
                }
                return response.body();
            } finally {
                if (!future.isDone()) future.cancel(true);
            }
        } catch (SubmissionException error) {
            throw error;
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            throw new SubmissionException(true);
        } catch (Exception error) {
            throw new SubmissionException(true);
        }
    }

    private static final class LimitedBody implements HttpResponse.BodySubscriber<String> {
        private final CompletableFuture<String> result = new CompletableFuture<>();
        private final ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        private Flow.Subscription subscription;
        public CompletionStage<String> getBody() { return result; }
        public void onSubscribe(Flow.Subscription subscription) { this.subscription = subscription; subscription.request(1); }
        public void onNext(List<ByteBuffer> buffers) {
            for (ByteBuffer buffer : buffers) {
                if (bytes.size() + (long) buffer.remaining() > 20_000_000) {
                    subscription.cancel(); result.completeExceptionally(new SubmissionException(true)); return;
                }
                byte[] chunk = new byte[buffer.remaining()]; buffer.get(chunk); bytes.writeBytes(chunk);
            }
            subscription.request(1);
        }
        public void onError(Throwable error) { result.completeExceptionally(error); }
        public void onComplete() { result.complete(bytes.toString(StandardCharsets.UTF_8)); }
    }
}
