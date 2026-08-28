package cn.sutone.cut.trigger.http;

import cn.sutone.cut.app.service.AnalysisReportService;
import cn.sutone.cut.domain.analysis.model.entity.AnalysisReportEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 分析报告接口（查询）。
 */
@RestController
@RequestMapping("/api/v1")
public class AnalysisReportController {

    private final AnalysisReportService analysisReportService;

    public AnalysisReportController(AnalysisReportService analysisReportService) {
        this.analysisReportService = analysisReportService;
    }

    @GetMapping("/projects/{projectId}/analysis")
    public AnalysisReportEntity queryByProject(@PathVariable Long projectId) {
        return analysisReportService.queryByProject(projectId);
    }

    @GetMapping("/analysis/{reportId}")
    public AnalysisReportEntity queryById(@PathVariable Long reportId) {
        return analysisReportService.queryById(reportId);
    }
}
