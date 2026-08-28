package cn.sutone.cut.infrastructure.persistence.mapper;

import cn.sutone.cut.domain.task.model.entity.TaskEntity;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.List;

/**
 * 异步任务表（task）MyBatis Mapper。
 */
public interface TaskMapper {

    @Insert("INSERT INTO task (project_id, type, status, progress, payload_json, result_json, error_msg, heartbeat_at) "
            + "VALUES (#{projectId}, #{type}, #{status}, #{progress}, #{payloadJson}, #{resultJson}, #{errorMsg}, #{heartbeatAt})")
    @Options(useGeneratedKeys = true, keyProperty = "taskId")
    int insert(TaskEntity task);

    @Select("SELECT id AS taskId, project_id, type, status, progress, payload_json, result_json, error_msg, heartbeat_at, created_at, updated_at "
            + "FROM task WHERE id = #{taskId}")
    TaskEntity selectById(@Param("taskId") Long taskId);

    @Update("UPDATE task SET status = #{status}, progress = #{progress}, result_json = #{resultJson}, "
            + "error_msg = #{errorMsg}, heartbeat_at = #{heartbeatAt}, updated_at = #{updatedAt} "
            + "WHERE id = #{taskId}")
    int update(TaskEntity task);

    @Select("SELECT id AS taskId, project_id, type, status, progress, payload_json, result_json, error_msg, heartbeat_at, created_at, updated_at "
            + "FROM task WHERE project_id = #{projectId} ORDER BY id DESC LIMIT #{limit}")
    List<TaskEntity> selectLatestByProjectId(@Param("projectId") Long projectId, @Param("limit") int limit);
}
