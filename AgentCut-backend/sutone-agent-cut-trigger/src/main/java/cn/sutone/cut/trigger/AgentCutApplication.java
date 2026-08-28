package cn.sutone.cut.trigger;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * AgentCut 后端启动类（放在 trigger 模块，确保 Controller 与应用服务同处运行 classpath）。
 *
 * <p>通过 {@code scanBasePackages = "cn.sutone.cut"} 扫描全部模块
 * （trigger/domain/infrastructure/app 等）的 Spring Bean。</p>
 */
@SpringBootApplication(scanBasePackages = "cn.sutone.cut")
public class AgentCutApplication {

    public static void main(String[] args) {
        SpringApplication.run(AgentCutApplication.class, args);
    }
}
