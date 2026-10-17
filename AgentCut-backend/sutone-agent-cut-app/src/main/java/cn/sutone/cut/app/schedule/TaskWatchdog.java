package cn.sutone.cut.app.schedule;

import cn.sutone.cut.domain.task.adapter.repository.ITaskRepository;
import cn.sutone.cut.domain.task.model.entity.TaskEntity;
import cn.sutone.cut.domain.task.model.valobj.enums.TaskStatus;
import cn.sutone.cut.domain.task.service.TaskDomainService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 任务看门狗：回收心跳超时的 RUNNING 任务。
 *
 * <p>背景——Python 分析服务的 job 状态保存在进程内存（{@code _jobs} 字典），一旦该服务重启
 * 或崩溃，完成回调永远不会到来。此前后端没有任何超时机制，任务会永久停在 PENDING/RUNNING，
 * 前端则永远显示「进行中」。</p>
 *
 * <p>判活依据是 {@code TaskEntity.heartbeatAt}：Python 每推送一条进度事件都会经
 * {@code TaskEntity.updateProgress} 刷新心跳。因此只要分析在推进，心跳就是新的。</p>
 *
 * <p><b>超时值必须大于 Python 侧的最坏静默窗口。</b>该窗口已被两件事压小：</p>
 * <ul>
 *   <li>Python 单次模型调用收紧为
 *       {@code AGENTCUT_AI_MODEL_TIMEOUT(120s) × (AGENTCUT_AI_MODEL_MAX_RETRIES(1) + 1)} = 240s；</li>
 *   <li>方案生成的 QA 循环每轮生成/质检都上报一次进度，不再有「整段 600s 预算全程静默」。</li>
 * </ul>
 * <p>因此静默窗口 ≈ 单次模型调用（240s）。默认取 600s 留 2.5 倍余量：既不会误杀正常的长耗时
 * 方案生成，又能让真正卡死的任务在 10 分钟内被判失败（此前是永久吊死）。</p>
 */
@Slf4j
@Component
public class TaskWatchdog {

    private final ITaskRepository taskRepository;
    private final TaskDomainService taskDomainService;

    /** 心跳超时阈值（秒）。 */
    @Value("${agentcut.task.watchdog.timeout-seconds:600}")
    private long timeoutSeconds;

    public TaskWatchdog(ITaskRepository taskRepository, TaskDomainService taskDomainService) {
        this.taskRepository = taskRepository;
        this.taskDomainService = taskDomainService;
    }

    /** 周期性扫描 RUNNING 任务，心跳超时即标记失败。 */
    @Scheduled(
            fixedDelayString = "${agentcut.task.watchdog.delay-ms:60000}",
            initialDelayString = "${agentcut.task.watchdog.initial-delay-ms:60000}")
    public void reapStaleTasks() {
        LocalDateTime deadline = LocalDateTime.now().minusSeconds(timeoutSeconds);
        List<TaskEntity> running = taskRepository.queryByStatus(TaskStatus.RUNNING);
        if (running.isEmpty()) {
            return;
        }
        for (TaskEntity task : running) {
            LocalDateTime heartbeat = task.getHeartbeatAt();
            // heartbeatAt 为 null 也视为超时：startRunning() 会立即打心跳，正常路径下不应为 null
            if (heartbeat == null || heartbeat.isBefore(deadline)) {
                log.warn("任务 {} 心跳超时（heartbeatAt={}, 阈值 {}s），标记为 FAILED",
                        task.getTaskId(), heartbeat, timeoutSeconds);
                taskDomainService.markFailed(
                        task.getTaskId(),
                        "分析超时：超过 " + timeoutSeconds + "s 未收到进度心跳（Python 服务可能已中断）");
            }
        }
    }
}
