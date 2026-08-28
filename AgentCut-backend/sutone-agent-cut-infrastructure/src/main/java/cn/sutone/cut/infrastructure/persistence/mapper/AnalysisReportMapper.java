package cn.sutone.cut.infrastructure.persistence.mapper;

import cn.sutone.cut.domain.analysis.model.entity.AnalysisReportEntity;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * 分析报告表（analysis_report）MyBatis Mapper。
 */
public interface AnalysisReportMapper {

    @Insert("INSERT INTO analysis_report (project_id, version, content_json, status) "
            + "VALUES (#{projectId}, #{version}, #{contentJson}, #{status})")
    @Options(useGeneratedKeys = true, keyProperty = "reportId")
    int insert(AnalysisReportEntity report);

    @Select("SELECT id AS reportId, project_id, version, content_json, status, created_at "
            + "FROM analysis_report WHERE id = #{reportId}")
    AnalysisReportEntity selectById(@Param("reportId") Long reportId);

    @Select("SELECT id AS reportId, project_id, version, content_json, status, created_at "
            + "FROM analysis_report WHERE project_id = #{projectId}")
    List<AnalysisReportEntity> selectByProjectId(@Param("projectId") Long projectId);
}
