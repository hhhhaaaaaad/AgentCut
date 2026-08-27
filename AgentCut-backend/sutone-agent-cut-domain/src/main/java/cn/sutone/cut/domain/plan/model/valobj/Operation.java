package cn.sutone.cut.domain.plan.model.valobj;

/**
 * 剪辑操作（判别联合的根接口）。
 *
 * <p>每种操作对应一个实现类，通过 {@link #type()} 区分，字段与 plan-schema.json 对齐。</p>
 */
public interface Operation {

    /** 操作类型 */
    OperationType type();
}
