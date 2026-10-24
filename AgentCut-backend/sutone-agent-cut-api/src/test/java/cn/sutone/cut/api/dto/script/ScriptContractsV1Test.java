package cn.sutone.cut.api.dto.script;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.stream.Stream;
import java.util.stream.StreamSupport;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class ScriptContractsV1Test {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final Path CORPUS = Path.of("..", "..", "docs", "contracts", "script-contracts-v1.fixtures.json");

    static Stream<Arguments> cases() throws Exception {
        JsonNode corpus = JSON.readTree(Files.readString(CORPUS));
        return StreamSupport.stream(corpus.get("cases").spliterator(), false).map(sample -> {
            JsonNode value = corpus.get("base").deepCopy();
            for (JsonNode patch : sample.get("patches")) {
                JsonNode parent = value, path = patch.get("path");
                for (int i = 0; i < path.size() - 1; i++) parent = parent.isArray() ? parent.get(path.get(i).asInt()) : parent.get(path.get(i).asText());
                JsonNode key = path.get(path.size() - 1);
                if (patch.get("op").asText().equals("remove")) {
                    if (parent.isArray()) ((ArrayNode) parent).remove(key.asInt());
                    else ((ObjectNode) parent).remove(key.asText());
                } else if (parent.isArray()) ((ArrayNode) parent).set(key.asInt(), patch.get("value").deepCopy());
                else ((ObjectNode) parent).set(key.asText(), patch.get("value").deepCopy());
            }
            return Arguments.of(sample.get("name").asText(), sample.get("valid").asBoolean(), value);
        });
    }

    @ParameterizedTest(name = "{0}")
    @MethodSource("cases")
    void sharedCorpus(String name, boolean valid, JsonNode value) throws Exception {
        String json = JSON.writeValueAsString(value);
        if (valid) {
            var result = ScriptContractsV1.parseBundle(json);
            ScriptContractsV1.parseBundle(JSON.writeValueAsString(result));
        } else {
            assertThrows(IllegalArgumentException.class, () -> ScriptContractsV1.parseBundle(json), name);
        }
    }

    @Test
    void readsTypedDtosWithoutChangingLegacyPlanContract() throws Exception {
        var result = ScriptContractsV1.parseBundle(JSON.readTree(Files.readString(CORPUS)).get("base").toString());
        assertEquals("unit_1", result.decision().rows().get(0).sourceUnitRefs().get(0));
        assertEquals(3, result.materialIndex().indexVersion());
        assertEquals("READY", result.script().reviewStatus());
        assertEquals(8000, result.script().rows().get(1).outputRange().startMs());
        assertEquals("SUCCESS", result.events().get(2).executionStatus());
    }

    @Test
    void acceptsProgramBuiltIdDirectorDraft() throws Exception {
        Path example = CORPUS.resolveSibling("offline-id-director.bundle.json");
        var result = ScriptContractsV1.parseBundle(Files.readString(example));
        assertEquals(5, result.materialIndex().scenes().size());
        assertEquals(6000, result.script().estimatedDurationMs());
        assertEquals("NEEDS_REVIEW", result.script().reviewStatus());
        assertEquals(4500, result.script().rows().get(1).sourceParts().get(0).sourceRange().startMs());
        assertEquals(3000, result.script().rows().get(1).outputRange().startMs());
        assertEquals(0, result.script().captionCues().size());
    }
}
