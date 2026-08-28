package cn.sutone.cut.infrastructure.persistence.mapper;

import cn.sutone.cut.domain.project.model.entity.ProjectEntity;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.List;

/**
 * 项目表（project）MyBatis Mapper。
 */
public interface ProjectMapper {

    @Insert("INSERT INTO project (user_id, title, source_asset_id, status, created_at, updated_at) "
            + "VALUES (#{userId}, #{title}, #{sourceAssetId}, #{status}, #{createdAt}, #{updatedAt})")
    @Options(useGeneratedKeys = true, keyProperty = "projectId")
    int insert(ProjectEntity project);

    @Select("SELECT id AS projectId, user_id, title, source_asset_id, status, created_at, updated_at "
            + "FROM project WHERE id = #{projectId}")
    ProjectEntity selectById(@Param("projectId") Long projectId);

    @Select("SELECT id AS projectId, user_id, title, source_asset_id, status, created_at, updated_at "
            + "FROM project WHERE user_id = #{userId}")
    List<ProjectEntity> selectByUserId(@Param("userId") Long userId);

    @Update("UPDATE project SET title = #{title}, status = #{status}, source_asset_id = #{sourceAssetId}, "
            + "updated_at = #{updatedAt} WHERE id = #{projectId}")
    int update(ProjectEntity project);

    @Delete("DELETE FROM project WHERE id = #{projectId}")
    int delete(@Param("projectId") Long projectId);
}
