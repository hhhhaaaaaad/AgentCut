package cn.sutone.cut.infrastructure.persistence.analysis;

import cn.sutone.cut.domain.analysis.adapter.repository.IAnalysisReportRepository;
import cn.sutone.cut.domain.analysis.model.entity.AnalysisReportEntity;
import cn.sutone.cut.infrastructure.persistence.mapper.AnalysisReportMapper;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Repository;

import java.util.List;

/**
 * 分析报告仓储 MyBatis 实现（mysql profile）。
 */
@Repository
@Profile("mysql")
public class MybatisAnalysisReportRepository implements IAnalysisReportRepository {

    private final AnalysisReportMapper analysisReportMapper;

    public MybatisAnalysisReportRepository(AnalysisReportMapper analysisReportMapper) {
        this.analysisReportMapper = analysisReportMapper;
    }

    @Override
    public void save(AnalysisReportEntity report) {
        analysisReportMapper.insert(report);
    }

    @Override
    public AnalysisReportEntity queryById(Long reportId) {
        return analysisReportMapper.selectById(reportId);
    }

    @Override
    public List<AnalysisReportEntity> queryByProjectId(Long projectId) {
        return analysisReportMapper.selectByProjectId(projectId);
    }
}
