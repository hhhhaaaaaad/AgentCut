package cn.sutone.cut.trigger.http;

import cn.sutone.cut.app.service.AnalysisReportService;
import cn.sutone.cut.domain.analysis.model.entity.AnalysisReportEntity;
import cn.sutone.cut.domain.analysis.model.valobj.AnalysisFlags;
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

    /**
     * 分析可信度标志（降级 / 质量），供前端展示告警横幅。
     *
     * <p>单独开一个轻量端点：报告正文 contentJson 是原始 JSON 字符串，让前端自己去 parse
     * 会把解析失败风险留在 UI 层；这里在服务端统一解析一次。</p>
     */
    @GetMapping("/projects/{projectId}/analysis/flags")
    public AnalysisFlags queryFlags(@PathVariable Long projectId) {
        return analysisReportService.queryFlags(projectId);
    }
}
