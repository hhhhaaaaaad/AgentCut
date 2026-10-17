package cn.sutone.cut.app;

import cn.sutone.cut.app.service.AnalysisReportService;
import cn.sutone.cut.domain.analysis.model.entity.AnalysisReportEntity;
import cn.sutone.cut.domain.analysis.model.valobj.AnalysisFlags;
import cn.sutone.cut.infrastructure.persistence.analysis.InMemoryAnalysisReportRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 分析可信度标志解析单元测试（降级 / 质量 → 前端告警横幅的数据来源）。
 */
class AnalysisReportServiceTest {

    private final InMemoryAnalysisReportRepository repository = new InMemoryAnalysisReportRepository();
    private final AnalysisReportService service =
            new AnalysisReportService(repository, new ObjectMapper());

    private void saveReport(Long projectId, String contentJson, String qualityJson) {
        repository.save(AnalysisReportEntity.builder()
                .projectId(projectId)
                .version(1)
                .contentJson(contentJson)
                .qualityJson(qualityJson)
                .status("SUCCESS")
                .build());
    }

    @Test
    void reportsSimulatedFromContentJson() {
        saveReport(1L, "{\"simulated\":true}", null);

        AnalysisFlags flags = service.queryFlags(1L);

        assertTrue(flags.isSimulated());
        assertFalse(flags.isQualityAvailable());
    }

    @Test
    void reportsQualityFailure() {
        saveReport(1L, "{\"simulated\":false}",
                "{\"passed\":false,\"overallScore\":0.7,\"issues\":[]}");

        AnalysisFlags flags = service.queryFlags(1L);

        assertFalse(flags.isSimulated());
        assertTrue(flags.isQualityAvailable());
        assertEquals(Boolean.FALSE, flags.getQualityPassed());
        assertEquals(0.7, flags.getOverallScore(), 1e-6);
    }

    @Test
    void returnsEmptyFlagsWhenNoReportExists() {
        AnalysisFlags flags = service.queryFlags(42L);

        assertFalse(flags.isSimulated());
        assertFalse(flags.isQualityAvailable());
        assertNull(flags.getQualityPassed());
    }

    @Test
    void survivesMalformedJson() {
        // 报告 JSON 损坏时必须静默降级为「无告警」，绝不能把接口弄挂
        saveReport(1L, "{not json", "also-not-json");

        AnalysisFlags flags = service.queryFlags(1L);

        assertFalse(flags.isSimulated());
        assertFalse(flags.isQualityAvailable());
    }

    @Test
    void handlesBlankAndLiteralNullQuality() {
        saveReport(1L, "", "null");

        AnalysisFlags flags = service.queryFlags(1L);

        assertFalse(flags.isSimulated());
        assertFalse(flags.isQualityAvailable());
    }
}
