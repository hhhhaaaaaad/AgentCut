package cn.sutone.cut.app.service;

import cn.sutone.cut.domain.analysis.adapter.repository.IAnalysisReportRepository;
import cn.sutone.cut.domain.analysis.model.entity.AnalysisReportEntity;
import org.springframework.stereotype.Service;

import java.util.Comparator;
import java.util.List;

/**
 * 分析报告应用服务：按项目查最新 / 按 ID 查。
 */
@Service
public class AnalysisReportService {

    private final IAnalysisReportRepository analysisReportRepository;

    public AnalysisReportService(IAnalysisReportRepository analysisReportRepository) {
        this.analysisReportRepository = analysisReportRepository;
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
}
