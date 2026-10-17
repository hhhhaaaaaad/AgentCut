package cn.sutone.cut.app;

import cn.sutone.cut.domain.task.adapter.repository.ITaskRepository;
import cn.sutone.cut.domain.task.model.entity.TaskEntity;
import cn.sutone.cut.domain.task.model.valobj.enums.TaskStatus;
import cn.sutone.cut.domain.task.model.valobj.enums.TaskType;
import cn.sutone.cut.domain.task.service.TaskDomainService;
import cn.sutone.cut.infrastructure.persistence.task.InMemoryTaskRepository;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

/**
 * 任务领域服务状态流转单元测试。
 */
class TaskDomainServiceTest {

    private final ITaskRepository repository = new InMemoryTaskRepository();
    private final TaskDomainService service = new TaskDomainService(repository);

    @Test
    void createPendingSetsPendingAndZeroProgress() {
        TaskEntity task = service.createPending(1L, TaskType.RENDER, "{\"projectId\":1}");

        assertNotNull(task.getTaskId());
        assertEquals(TaskStatus.PENDING, task.getStatus());
        assertEquals(0, task.getProgress());
        assertEquals(TaskType.RENDER, task.getType());
    }

    @Test
    void startTransitionsToRunning() {
        TaskEntity task = service.createPending(1L, TaskType.RENDER, "{}");

        service.start(task.getTaskId());

        assertEquals(TaskStatus.RUNNING, repository.queryById(task.getTaskId()).getStatus());
    }

    @Test
    void markSuccessSetsResultAndFullProgress() {
        TaskEntity task = service.createPending(1L, TaskType.RENDER, "{}");

        service.markSuccess(task.getTaskId(), "{\"outputPath\":\"out.mp4\"}");

        TaskEntity loaded = repository.queryById(task.getTaskId());
        assertEquals(TaskStatus.SUCCESS, loaded.getStatus());
        assertEquals(100, loaded.getProgress());
        assertEquals("{\"outputPath\":\"out.mp4\"}", loaded.getResultJson());
    }

    @Test
    void markFailedSetsErrorAndKeepsFailedStatus() {
        TaskEntity task = service.createPending(1L, TaskType.ANALYZE, "{}");

        service.markFailed(task.getTaskId(), "boom");

        TaskEntity loaded = repository.queryById(task.getTaskId());
        assertEquals(TaskStatus.FAILED, loaded.getStatus());
        assertEquals("boom", loaded.getErrorMsg());
    }

    @Test
    void updateProgressSetsProgressStepAndHeartbeat() {
        TaskEntity task = service.createPending(1L, TaskType.ANALYZE, "{}");

        service.updateProgress(task.getTaskId(), 42, "语音转写 1/2");

        TaskEntity loaded = repository.queryById(task.getTaskId());
        assertEquals(42, loaded.getProgress());
        assertEquals("语音转写 1/2", loaded.getStep());
        assertNotNull(loaded.getHeartbeatAt());
    }

    @Test
    void updateProgressTransitionsPendingToRunning() {
        TaskEntity task = service.createPending(1L, TaskType.ANALYZE, "{}");

        service.updateProgress(task.getTaskId(), 10, "初始化");

        assertEquals(TaskStatus.RUNNING, repository.queryById(task.getTaskId()).getStatus());
    }

    @Test
    void updateProgressClampsOutOfRangeValues() {
        TaskEntity task = service.createPending(1L, TaskType.ANALYZE, "{}");

        service.updateProgress(task.getTaskId(), 150, "x");

        assertEquals(100, repository.queryById(task.getTaskId()).getProgress());
    }

    @Test
    void updateProgressDoesNotReviveSuccessfulTask() {
        TaskEntity task = service.createPending(1L, TaskType.ANALYZE, "{}");
        service.markSuccess(task.getTaskId(), "{\"ok\":true}");

        service.updateProgress(task.getTaskId(), 25, "迟到进度");

        TaskEntity loaded = repository.queryById(task.getTaskId());
        assertEquals(TaskStatus.SUCCESS, loaded.getStatus());
        assertEquals(100, loaded.getProgress());
        assertEquals("{\"ok\":true}", loaded.getResultJson());
    }

    @Test
    void updateProgressDoesNotReviveFailedTask() {
        TaskEntity task = service.createPending(1L, TaskType.ANALYZE, "{}");
        service.markFailed(task.getTaskId(), "原始失败");

        service.updateProgress(task.getTaskId(), 25, "迟到进度");

        TaskEntity loaded = repository.queryById(task.getTaskId());
        assertEquals(TaskStatus.FAILED, loaded.getStatus());
        assertEquals("原始失败", loaded.getErrorMsg());
    }

    @Test
    void updateProgressIgnoresUnknownTask() {
        // 进度来自外部回调，任务可能已不存在——必须静默忽略而不是抛异常
        service.updateProgress(999L, 50, "x");
    }

    @Test
    void startSetsInitialHeartbeat() {
        TaskEntity task = service.createPending(1L, TaskType.ANALYZE, "{}");

        service.start(task.getTaskId());

        // 心跳必须非空：否则 RUNNING 任务会被看门狗瞬间判为超时并误杀
        assertNotNull(repository.queryById(task.getTaskId()).getHeartbeatAt());
    }
}
