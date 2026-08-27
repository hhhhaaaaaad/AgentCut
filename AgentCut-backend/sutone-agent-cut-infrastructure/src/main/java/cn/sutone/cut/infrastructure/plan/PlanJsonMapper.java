package cn.sutone.cut.infrastructure.plan;

import cn.sutone.cut.domain.plan.model.entity.PlanEntity;
import cn.sutone.cut.domain.plan.model.valobj.OpCrop;
import cn.sutone.cut.domain.plan.model.valobj.OpMute;
import cn.sutone.cut.domain.plan.model.valobj.OpSpeed;
import cn.sutone.cut.domain.plan.model.valobj.OpSubtitle;
import cn.sutone.cut.domain.plan.model.valobj.OpVolume;
import cn.sutone.cut.domain.plan.model.valobj.Operation;
import com.fasterxml.jackson.annotation.JsonSubTypes;
import com.fasterxml.jackson.annotation.JsonTypeInfo;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Component;

/**
 * 方案 JSON 序列化器。
 *
 * <p>领域层保持框架无关（不含 Jackson 注解），在此用 mix-in 方式为 {@link Operation}
 * 判别联合配置多态反序列化，使方案 JSON 与 plan-schema.json 的 "type" 判别字段对齐。</p>
 */
@Component
public class PlanJsonMapper {

    private final ObjectMapper objectMapper;

    public PlanJsonMapper() {
        this.objectMapper = new ObjectMapper();
        objectMapper.addMixIn(Operation.class, OperationMixin.class);
    }

    public String toJson(PlanEntity plan) throws Exception {
        return objectMapper.writeValueAsString(plan);
    }

    public PlanEntity fromJson(String json) throws Exception {
        return objectMapper.readValue(json, PlanEntity.class);
    }

    /**
     * Operation 多态 mix-in：用 "type" 字段作为判别器。
     */
    @JsonTypeInfo(use = JsonTypeInfo.Id.NAME, include = JsonTypeInfo.As.PROPERTY, property = "type")
    @JsonSubTypes({
            @JsonSubTypes.Type(value = OpSpeed.class, name = "speed"),
            @JsonSubTypes.Type(value = OpCrop.class, name = "crop"),
            @JsonSubTypes.Type(value = OpSubtitle.class, name = "subtitle"),
            @JsonSubTypes.Type(value = OpVolume.class, name = "volume"),
            @JsonSubTypes.Type(value = OpMute.class, name = "mute")
    })
    private abstract static class OperationMixin {
    }
}
