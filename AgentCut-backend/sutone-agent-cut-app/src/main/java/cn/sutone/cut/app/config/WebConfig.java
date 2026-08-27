package cn.sutone.cut.app.config;

import cn.sutone.cut.domain.plan.model.valobj.OpCrop;
import cn.sutone.cut.domain.plan.model.valobj.OpMute;
import cn.sutone.cut.domain.plan.model.valobj.OpSpeed;
import cn.sutone.cut.domain.plan.model.valobj.OpSubtitle;
import cn.sutone.cut.domain.plan.model.valobj.OpVolume;
import cn.sutone.cut.domain.plan.model.valobj.Operation;
import com.fasterxml.jackson.annotation.JsonSubTypes;
import com.fasterxml.jackson.annotation.JsonTypeInfo;
import org.springframework.boot.autoconfigure.jackson.Jackson2ObjectMapperBuilderCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * Web 全局配置：跨域 + Operation 多态反序列化。
 *
 * <p>通过 mix-in 让 Spring 的 ObjectMapper 能反序列化 Operation 判别联合，
 * 这样 {@code @RequestBody PlanEntity} 也能正确解析方案 JSON。</p>
 */
@Configuration
public class WebConfig {

    /** 全局跨域（单机联调用，生产需收紧） */
    @Bean
    public WebMvcConfigurer corsConfigurer() {
        return new WebMvcConfigurer() {
            @Override
            public void addCorsMappings(CorsRegistry registry) {
                registry.addMapping("/**")
                        .allowedOriginPatterns("*")
                        .allowedMethods("GET", "POST", "PUT", "DELETE", "OPTIONS")
                        .allowedHeaders("*");
            }
        };
    }

    /** 给 Spring ObjectMapper 注册 Operation 多态 mix-in */
    @Bean
    public Jackson2ObjectMapperBuilderCustomizer operationMixInCustomizer() {
        return builder -> builder.mixIn(Operation.class, OperationTypeMixin.class);
    }

    @JsonTypeInfo(use = JsonTypeInfo.Id.NAME, include = JsonTypeInfo.As.PROPERTY, property = "type")
    @JsonSubTypes({
            @JsonSubTypes.Type(value = OpSpeed.class, name = "speed"),
            @JsonSubTypes.Type(value = OpCrop.class, name = "crop"),
            @JsonSubTypes.Type(value = OpSubtitle.class, name = "subtitle"),
            @JsonSubTypes.Type(value = OpVolume.class, name = "volume"),
            @JsonSubTypes.Type(value = OpMute.class, name = "mute")
    })
    private abstract static class OperationTypeMixin {
    }
}
