package cn.sutone.cut.infrastructure.persistence.analysis;

import cn.sutone.cut.domain.analysis.adapter.repository.IAnalysisReportRepository;
import cn.sutone.cut.domain.analysis.model.entity.AnalysisReportEntity;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

/**
 * 分析报告仓储 MVP 内存实现。后续替换为 MyBatis Mapper。
 */
@Repository
public class InMemoryAnalysisReportRepository implements IAnalysisReportRepository {

    private final Map<Long, AnalysisReportEntity> store = new ConcurrentHashMap<>();
    private final AtomicLong idGen = new AtomicLong(1);

    @Override
    public void save(AnalysisReportEntity report) {
        if (report.getReportId() == null) {
            report.setReportId(idGen.getAndIncrement());
        }
        store.put(report.getReportId(), report);
    }

    @Override
    public AnalysisReportEntity queryById(Long reportId) {
        return store.get(reportId);
    }

    @Override
    public List<AnalysisReportEntity> queryByProjectId(Long projectId) {
        return store.values().stream().filter(r -> projectId.equals(r.getProjectId())).toList();
    }
}
