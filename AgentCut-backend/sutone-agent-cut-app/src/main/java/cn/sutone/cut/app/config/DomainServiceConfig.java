package cn.sutone.cut.app.config;

import cn.sutone.cut.domain.plan.adapter.repository.IPlanRepository;
import cn.sutone.cut.domain.plan.service.PlanDomainService;
import cn.sutone.cut.domain.project.adapter.repository.IProjectRepository;
import cn.sutone.cut.domain.project.service.ProjectDomainService;
import cn.sutone.cut.domain.render.service.RenderPlanService;
import cn.sutone.cut.domain.task.adapter.repository.ITaskRepository;
import cn.sutone.cut.domain.task.service.TaskDomainService;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * 领域服务装配配置。
 *
 * <p>领域层保持框架无关（不引 Spring 注解），在此统一把领域服务装配为 Spring Bean。</p>
 */
@Configuration
public class DomainServiceConfig {

    @Bean
    public PlanDomainService planDomainService(IPlanRepository planRepository) {
        return new PlanDomainService(planRepository);
    }

    @Bean
    public TaskDomainService taskDomainService(ITaskRepository taskRepository) {
        return new TaskDomainService(taskRepository);
    }

    @Bean
    public ProjectDomainService projectDomainService(IProjectRepository projectRepository) {
        return new ProjectDomainService(projectRepository);
    }

    @Bean
    public RenderPlanService renderPlanService() {
        return new RenderPlanService();
    }
}
