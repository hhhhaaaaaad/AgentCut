package cn.sutone.cut.app.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.nio.file.Files;
import java.nio.file.Path;

/** Operator-owned B2 OfflineDirectorInput files; never accepts a client filesystem path. */
@Component
public class PreparedScriptCatalog {
    private final Path root;
    private final ObjectMapper json;
    public PreparedScriptCatalog(@Value("${agentcut.script-tasks.prepared-dir:}") String root, ObjectMapper json) {
        this.root = root.isBlank() ? null : Path.of(root).toAbsolutePath().normalize();
        this.json = json.copy().enable(com.fasterxml.jackson.core.JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
                .enable(com.fasterxml.jackson.databind.DeserializationFeature.FAIL_ON_TRAILING_TOKENS);
    }
    public JsonNode load(String projectId, String assetId) {
        if (root == null) throw new ScriptTaskService.Problem(409, "PREPARED_INDEX_REQUIRED");
        if (!projectId.matches("[A-Za-z0-9_-]+") || !assetId.matches("[A-Za-z0-9_-]+")) {
            throw new ScriptTaskService.Problem(422, "INVALID_INPUT");
        }
        try {
            Path trustedRoot = root.toRealPath();
            Path file = trustedRoot.resolve(projectId).resolve(assetId + ".json").toRealPath();
            if (!file.startsWith(trustedRoot) || !Files.isRegularFile(file)) {
                throw new ScriptTaskService.Problem(422, "INVALID_PREPARED_INDEX");
            }
            byte[] bytes;
            try (var stream = Files.newInputStream(file)) { bytes = stream.readNBytes(5_000_001); }
            if (bytes.length > 5_000_000) throw new ScriptTaskService.Problem(413, "PREPARED_INDEX_TOO_LARGE");
            JsonNode prepared = json.readTree(bytes);
            if (prepared == null || !prepared.isObject() || !prepared.path("submission").isObject()
                    || !prepared.path("sourceIndex").isObject() || !prepared.path("evidence").isObject()) {
                throw new ScriptTaskService.Problem(422, "INVALID_PREPARED_INDEX");
            }
            cn.sutone.cut.api.dto.script.ScriptContractsV1.validateStructure("AssetRef", prepared.path("sourceIndex").path("assetRef"));
            if (!prepared.path("submission").path("projectId").asText().equals(projectId)
                    || !prepared.path("sourceIndex").path("assetRef").path("assetId").asText().equals(assetId)) {
                throw new ScriptTaskService.Problem(422, "PREPARED_INDEX_OWNERSHIP_MISMATCH");
            }
            return prepared;
        } catch (ScriptTaskService.Problem error) {
            throw error;
        } catch (java.nio.file.NoSuchFileException error) {
            throw new ScriptTaskService.Problem(409, "PREPARED_INDEX_REQUIRED");
        } catch (Exception error) {
            throw new ScriptTaskService.Problem(422, "INVALID_PREPARED_INDEX");
        }
    }
}
