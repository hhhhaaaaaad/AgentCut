package cn.sutone.cut.app;

import cn.sutone.cut.app.schedule.TaskWatchdog;
import cn.sutone.cut.domain.task.adapter.repository.ITaskRepository;
import cn.sutone.cut.domain.task.model.entity.TaskEntity;
import cn.sutone.cut.domain.task.model.valobj.enums.TaskStatus;
import cn.sutone.cut.domain.task.model.valobj.enums.TaskType;
import cn.sutone.cut.domain.task.service.TaskDomainService;
import cn.sutone.cut.infrastructure.persistence.task.InMemoryTaskRepository;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.LocalDateTime;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

/**
 * 任务看门狗单元测试：心跳超时必须把 RUNNING 任务判为 FAILED，心跳新鲜则不动。
 */
class TaskWatchdogTest {

    private final ITaskRepository repository = new InMemoryTaskRepository();
    private final TaskDomainService service = new TaskDomainService(repository);

    private TaskWatchdog watchdogWithTimeout(long seconds) {
        TaskWatchdog watchdog = new TaskWatchdog(repository, service);
        ReflectionTestUtils.setField(watchdog, "timeoutSeconds", seconds);
        return watchdog;
    }

    @Test
    void marksRunningTaskFailedWhenHeartbeatStale() {
        TaskEntity task = service.createPending(1L, TaskType.ANALYZE, "{}");
        service.start(task.getTaskId());
        // 把心跳改到很久以前，模拟 Python 服务中断后再无进度上报
        TaskEntity loaded = repository.queryById(task.getTaskId());
        loaded.setHeartbeatAt(LocalDateTime.now().minusSeconds(3600));
        repository.update(loaded);

        watchdogWithTimeout(60).reapStaleTasks();

        TaskEntity after = repository.queryById(task.getTaskId());
        assertEquals(TaskStatus.FAILED, after.getStatus());
        assertNotNull(after.getErrorMsg());
    }

    @Test
    void keepsRunningTaskWhenHeartbeatFresh() {
        TaskEntity task = service.createPending(1L, TaskType.ANALYZE, "{}");
        service.start(task.getTaskId());

        watchdogWithTimeout(60).reapStaleTasks();

        assertEquals(TaskStatus.RUNNING, repository.queryById(task.getTaskId()).getStatus());
    }

    @Test
    void treatsNullHeartbeatAsStale() {
        TaskEntity task = service.createPending(1L, TaskType.ANALYZE, "{}");
        task.startRunning();
        task.setHeartbeatAt(null); // 绕过 startRunning 的补心跳，模拟异常数据
        repository.update(task);

        watchdogWithTimeout(60).reapStaleTasks();

        assertEquals(TaskStatus.FAILED, repository.queryById(task.getTaskId()).getStatus());
    }

    @Test
    void ignoresNonRunningTasks() {
        service.createPending(1L, TaskType.ANALYZE, "{}");

        watchdogWithTimeout(60).reapStaleTasks();

        // PENDING 任务不在看门狗职责范围内
        assertEquals(TaskStatus.PENDING,
                repository.queryLatestByProjectId(1L, 1).get(0).getStatus());
    }
}
