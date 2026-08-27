package cn.sutone.cut.domain.analysis.adapter.repository;

import cn.sutone.cut.domain.analysis.model.entity.AnalysisReportEntity;

import java.util.List;

/**
 * 分析报告仓储接口。
 */
public interface IAnalysisReportRepository {

    void save(AnalysisReportEntity report);

    AnalysisReportEntity queryById(Long reportId);

    List<AnalysisReportEntity> queryByProjectId(Long projectId);
}
