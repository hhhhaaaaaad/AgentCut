package cn.sutone.cut.app.service;

import cn.sutone.cut.domain.analysis.adapter.repository.IAnalysisReportRepository;
import cn.sutone.cut.domain.analysis.model.entity.AnalysisReportEntity;
import cn.sutone.cut.domain.analysis.model.valobj.AnalysisFlags;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.Comparator;
import java.util.List;

/**
 * 分析报告应用服务：按项目查最新 / 按 ID 查 / 解析降级与质量标志。
 */
@Slf4j
@Service
public class AnalysisReportService {

    private final IAnalysisReportRepository analysisReportRepository;
    private final ObjectMapper objectMapper;

    public AnalysisReportService(IAnalysisReportRepository analysisReportRepository,
                                 ObjectMapper objectMapper) {
        this.analysisReportRepository = analysisReportRepository;
        this.objectMapper = objectMapper;
    }

    /**
     * 查询项目最新一份分析报告（按 reportId 最大）。
     */
    public AnalysisReportEntity queryByProject(Long projectId) {
        List<AnalysisReportEntity> list = analysisReportRepository.queryByProjectId(projectId);
        return list.stream()
                .max(Comparator.comparing(AnalysisReportEntity::getReportId))
                .orElse(null);
    }

    public AnalysisReportEntity queryById(Long reportId) {
        return analysisReportRepository.queryById(reportId);
    }

    /**
     * 解析报告中的「降级 / 质量」标志，供前端展示告警横幅。
     *
     * <p>{@code contentJson} / {@code qualityJson} 都是原始 JSON 字符串，这里在服务端统一解析一次，
     * 前端不必承担 JSON.parse 的失败风险。解析失败一律降级为「无告警」，绝不因此抛错——
     * 告警是锦上添花，不能反过来把接口弄挂。</p>
     */
    public AnalysisFlags queryFlags(Long projectId) {
        AnalysisReportEntity report = queryByProject(projectId);
        if (report == null) {
            return AnalysisFlags.builder().projectId(projectId).build();
        }

        boolean simulated = false;
        Boolean qualityPassed = null;
        Double overallScore = null;

        try {
            JsonNode content = readTreeOrNull(report.getContentJson());
            if (content != null) {
                simulated = content.path("simulated").asBoolean(false);
            }
        } catch (Exception e) {
            log.warn("解析分析报告 contentJson 失败（projectId={}）：{}", projectId, e.getMessage());
        }

        try {
            JsonNode quality = readTreeOrNull(report.getQualityJson());
            if (quality != null && quality.isObject()) {
                if (quality.hasNonNull("passed")) {
                    qualityPassed = quality.get("passed").asBoolean();
                }
                if (quality.hasNonNull("overallScore")) {
                    overallScore = quality.get("overallScore").asDouble();
                }
            }
        } catch (Exception e) {
            log.warn("解析质量评审 qualityJson 失败（projectId={}）：{}", projectId, e.getMessage());
        }

        return AnalysisFlags.builder()
                .projectId(projectId)
                .simulated(simulated)
                .qualityAvailable(qualityPassed != null)
                .qualityPassed(qualityPassed)
                .overallScore(overallScore)
                .build();
    }

    /** JSON 为空串 / null 时返回 null（Jackson 的 readTree 对空串会抛异常）。 */
    private JsonNode readTreeOrNull(String json) throws Exception {
        if (json == null || json.isBlank()) {
            return null;
        }
        return objectMapper.readTree(json);
    }
}
