package cn.sutone.cut.app;

import cn.sutone.cut.domain.adapter.port.IScriptRunClient.SubmissionException;
import cn.sutone.cut.infrastructure.client.ScriptRunClient;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.*;

class ScriptRunClientTest {
    HttpServer server;
    @AfterEach void stop() { if (server != null) server.stop(0); }

    ScriptRunClient client() throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        return new ScriptRunClient("http://127.0.0.1:" + server.getAddress().getPort(), 1);
    }
    @ParameterizedTest
    @CsvSource({"400,false", "409,false", "422,false", "503,false", "500,true", "502,true", "302,true", "200,true"})
    void rejectionAndUncertainAreDistinctWithNoPostRetry(int status, boolean uncertain) throws Exception {
        var client = client();
        var count = new AtomicInteger();
        server.createContext("/v1/script-runs", exchange -> {
            count.incrementAndGet();
            assertEquals("POST", exchange.getRequestMethod());
            assertNull(exchange.getRequestHeaders().getFirst("Upgrade"));
            assertEquals("{\"prepared\":{}}", new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            byte[] data = "{}".getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(status, data.length);
            exchange.getResponseBody().write(data); exchange.close();
        });
        server.start();
        assertEquals(uncertain, assertThrows(SubmissionException.class, () -> client.submit("{\"prepared\":{}}")).uncertain());
        assertEquals(1, count.get());
    }

    @Test void reconciliationUsesGetAndPrivateRunToken() throws Exception {
        var client = client();
        server.createContext("/v1/script-runs/run_1", exchange -> {
            assertEquals("GET", exchange.getRequestMethod());
            assertEquals("private-token", exchange.getRequestHeaders().getFirst("X-AgentCut-Run-Token"));
            exchange.sendResponseHeaders(200, 2); exchange.getResponseBody().write("{}".getBytes()); exchange.close();
        });
        server.start();
        assertEquals("{}", client.status("run_1", "private-token"));
        assertThrows(IllegalArgumentException.class, () -> client.status("../another", "private-token"));
    }

    @Test void deadlineAlsoCoversBodyAfterSuccessfulHeaders() throws Exception {
        var client = client();
        CountDownLatch release = new CountDownLatch(1);
        server.createContext("/v1/script-runs", exchange -> {
            exchange.sendResponseHeaders(202, 1000);
            exchange.getResponseBody().write('{'); exchange.getResponseBody().flush();
            try { release.await(5, TimeUnit.SECONDS); } catch (InterruptedException ignored) { Thread.currentThread().interrupt(); }
            exchange.close();
        });
        server.start();
        long started = System.nanoTime();
        try {
            assertTrue(assertThrows(SubmissionException.class, () -> client.submit("{}")).uncertain());
            assertTrue(TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started) < 3000);
        } finally { release.countDown(); }
    }
}
