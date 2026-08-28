package cn.sutone.cut.infrastructure.persistence.mapper;

import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.List;

/**
 * 剪辑方案表（plan / plan_version）MyBatis Mapper。
 *
 * <p>方案内容（对齐 plan-schema.json 的 JSON 文档）存于 {@code plan_version.content_json}，
 * {@code plan.current_version_id} 指向当前生效版本；查询当前方案时 join 取回 JSON 再由
 * 仓储层用 PlanJsonMapper 反序列化。</p>
 */
public interface PlanMapper {

    @Insert("INSERT INTO plan (project_id, status) VALUES (#{projectId}, 'DRAFT') "
            + "ON DUPLICATE KEY UPDATE status = status")
    int upsertPlan(@Param("projectId") Long projectId);

    @Select("SELECT id FROM plan WHERE project_id = #{projectId}")
    Long selectPlanId(@Param("projectId") Long projectId);

    @Insert("INSERT INTO plan_version (plan_id, version_no, content_json, applied) "
            + "VALUES (#{planId}, #{versionNo}, #{contentJson}, 0) "
            + "ON DUPLICATE KEY UPDATE content_json = VALUES(content_json), applied = 0")
    int upsertVersion(@Param("planId") Long planId, @Param("versionNo") int versionNo,
                      @Param("contentJson") String contentJson);

    @Update("UPDATE plan SET current_version_id = "
            + "(SELECT id FROM plan_version WHERE plan_id = #{planId} AND version_no = #{versionNo}) "
            + "WHERE id = #{planId}")
    int updateCurrentVersion(@Param("planId") Long planId, @Param("versionNo") int versionNo);

    @Select("SELECT pv.content_json FROM plan p JOIN plan_version pv ON pv.id = p.current_version_id "
            + "WHERE p.project_id = #{projectId}")
    String selectCurrentContent(@Param("projectId") Long projectId);

    @Select("SELECT version_no FROM plan_version WHERE plan_id = #{planId} ORDER BY version_no ASC")
    List<Integer> selectVersionNumbers(@Param("planId") Long planId);

    @Select("SELECT content_json FROM plan_version WHERE plan_id = #{planId} AND version_no = #{versionNo}")
    String selectVersionContent(@Param("planId") Long planId, @Param("versionNo") int versionNo);
}
