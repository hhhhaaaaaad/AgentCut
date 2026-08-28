package cn.sutone.cut.infrastructure.persistence.mapper;

import cn.sutone.cut.domain.asset.model.entity.AssetEntity;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * 素材表（asset）MyBatis Mapper。
 */
public interface AssetMapper {

    @Insert("INSERT INTO asset (project_id, type, oss_url, file_name, size, duration, width, height, fps, created_at) "
            + "VALUES (#{projectId}, #{type}, #{ossUrl}, #{fileName}, #{size}, #{duration}, #{width}, #{height}, #{fps}, #{createdAt})")
    @Options(useGeneratedKeys = true, keyProperty = "assetId")
    int insert(AssetEntity asset);

    @Select("SELECT id AS assetId, project_id, type, oss_url, file_name, size, duration, width, height, fps, created_at "
            + "FROM asset WHERE id = #{assetId}")
    AssetEntity selectById(@Param("assetId") Long assetId);

    @Select("SELECT id AS assetId, project_id, type, oss_url, file_name, size, duration, width, height, fps, created_at "
            + "FROM asset WHERE project_id = #{projectId}")
    List<AssetEntity> selectByProjectId(@Param("projectId") Long projectId);

    @Delete("DELETE FROM asset WHERE id = #{assetId}")
    int delete(@Param("assetId") Long assetId);
}
