package cn.sutone.cut.app;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * AgentCut 后端启动类。
 *
 * <p>通过 {@code scanBasePackages = "cn.sutone.cut"} 扫描全部模块
 * （trigger/domain/infrastructure 等）的 Spring Bean。</p>
 */
@SpringBootApplication(scanBasePackages = "cn.sutone.cut")
public class AgentCutApplication {

    public static void main(String[] args) {
        SpringApplication.run(AgentCutApplication.class, args);
    }
}
