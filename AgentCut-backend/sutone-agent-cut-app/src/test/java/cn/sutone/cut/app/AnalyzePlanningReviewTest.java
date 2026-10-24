package cn.sutone.cut.app;

import cn.sutone.cut.app.service.AnalyzeTaskService;
import cn.sutone.cut.domain.plan.service.PlanDomainService;
import cn.sutone.cut.domain.task.model.entity.TaskEntity;
import cn.sutone.cut.domain.task.model.valobj.enums.TaskStatus;
import cn.sutone.cut.domain.task.model.valobj.enums.TaskType;
import cn.sutone.cut.domain.task.service.TaskDomainService;
import cn.sutone.cut.infrastructure.persistence.analysis.InMemoryAnalysisReportRepository;
import cn.sutone.cut.infrastructure.persistence.plan.InMemoryPlanRepository;
import cn.sutone.cut.infrastructure.persistence.task.InMemoryTaskRepository;
import cn.sutone.cut.infrastructure.plan.PlanJsonMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

/** 决策闭环到 Java 终态的最小离线联调，使用真实内存仓储与方案反序列化。 */
class AnalyzePlanningReviewTest {
    private static final String HASH = "a".repeat(64);
    private static final String PLAN = """
            {"schemaVersion":"1.0","planVersion":1,"projectId":"p",
             "source":{"assetId":"a","url":"file:///source.mp4","duration":10,
                       "width":1920,"height":1080,"fps":30},
             "global":{"output":{"width":1920,"height":1080,"fps":30}},
             "timeline":[{"id":"seg_1","keep":true,"sourceRange":{"start":0,"end":10},"operations":[]}],
             "transitions":[]}
            """;
    private final InMemoryTaskRepository tasks = new InMemoryTaskRepository();
    private final TaskDomainService taskService = new TaskDomainService(tasks);
    private final InMemoryAnalysisReportRepository reports = new InMemoryAnalysisReportRepository();
    private final InMemoryPlanRepository plans = new InMemoryPlanRepository();
    private final AnalyzeTaskService service = new AnalyzeTaskService(
            null, null, tasks, taskService, null, reports,
            new PlanJsonMapper(), new PlanDomainService(plans));

    private TaskEntity task() {
        return taskService.createPending(1L, TaskType.ANALYZE, "{}");
    }

    private String readyReport() {
        return "{\"planning\":{\"reviewStatus\":\"READY\",\"selectedCandidateHash\":\"" + HASH + "\"}}";
    }

    private String quality(boolean passed) {
        return "{\"passed\":" + passed + ",\"candidateHash\":\"" + HASH + "\"}";
    }

    @Test
    void unavailableQaPersistsDraftAndTraceAsNeedsReview() {
        TaskEntity task = task();
        String report = "{\"planning\":{\"reviewStatus\":\"NEEDS_REVIEW\",\"reviewReasons\":[\"QA_UNAVAILABLE\"]}}";
        service.handleCallback(task.getTaskId(), report, PLAN, null);

        assertEquals(TaskStatus.NEEDS_REVIEW, tasks.queryById(task.getTaskId()).getStatus());
        assertEquals(PLAN, tasks.queryById(task.getTaskId()).getResultJson());
        assertEquals(report, reports.queryByProjectId(1L).get(0).getContentJson());
        assertEquals("NEEDS_REVIEW", reports.queryByProjectId(1L).get(0).getStatus());
        assertNotNull(plans.queryCurrentByProjectId("1"));
    }

    @Test
    void acceptedBoundReviewCompletesSuccessfully() {
        TaskEntity task = task();
        service.handleCallback(task.getTaskId(), readyReport(), PLAN, quality(true));
        assertEquals(TaskStatus.SUCCESS, tasks.queryById(task.getTaskId()).getStatus());
    }

    @Test
    void newTraceCannotHideFailedOrMissingQa() {
        TaskEntity failedQa = task();
        service.handleCallback(failedQa.getTaskId(), readyReport(), PLAN, quality(false));
        assertEquals(TaskStatus.NEEDS_REVIEW, tasks.queryById(failedQa.getTaskId()).getStatus());
        TaskEntity missingQa = task();
        service.handleCallback(missingQa.getTaskId(), readyReport(), PLAN, null);
        assertEquals(TaskStatus.NEEDS_REVIEW, tasks.queryById(missingQa.getTaskId()).getStatus());
    }

    @ParameterizedTest
    @ValueSource(strings = {"null", "{}", "{\"reviewStatus\":\"UNKNOWN\"}", "\"READY\""})
    void invalidNewReviewMetadataRequiresReview(String planning) {
        TaskEntity task = task();
        service.handleCallback(task.getTaskId(), "{\"planning\":" + planning + "}", PLAN, quality(true));
        assertEquals(TaskStatus.NEEDS_REVIEW, tasks.queryById(task.getTaskId()).getStatus());
    }

    @Test
    void staleCandidateReviewCannotMarkReady() {
        TaskEntity task = task();
        service.handleCallback(task.getTaskId(), readyReport(), PLAN,
                "{\"passed\":true,\"candidateHash\":\"" + "b".repeat(64) + "\"}");
        assertEquals(TaskStatus.NEEDS_REVIEW, tasks.queryById(task.getTaskId()).getStatus());
    }

    @Test
    void legacyReportWithoutPlanningKeepsCompatibility() {
        TaskEntity task = task();
        service.handleCallback(task.getTaskId(), "{\"simulated\":false}", PLAN, null);
        assertEquals(TaskStatus.SUCCESS, tasks.queryById(task.getTaskId()).getStatus());
    }

    @Test
    void lateReadyCallbackCannotReplaceNeedsReviewResult() {
        TaskEntity task = task();
        service.handleCallback(task.getTaskId(), "{\"planning\":{\"reviewStatus\":\"NEEDS_REVIEW\"}}", PLAN, null);
        service.handleCallback(task.getTaskId(), readyReport(), PLAN, quality(true));
        assertEquals(TaskStatus.NEEDS_REVIEW, tasks.queryById(task.getTaskId()).getStatus());
        assertEquals(1, reports.queryByProjectId(1L).size());
        assertEquals(1, plans.queryVersionNumbers("1").size());
    }
}
