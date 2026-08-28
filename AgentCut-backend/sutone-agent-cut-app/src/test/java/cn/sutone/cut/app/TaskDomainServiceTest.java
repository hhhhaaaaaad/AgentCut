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
}
