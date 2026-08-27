package cn.sutone.cut.domain.plan.model.valobj;

/**
 * 静音操作（无参数）。
 */
public class OpMute implements Operation {

    @Override
    public OperationType type() {
        return OperationType.MUTE;
    }
}
