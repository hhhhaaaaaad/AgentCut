package cn.sutone.cut.domain.plan.model.valobj;

/**
 * 剪辑操作类型（MVP 范围）。
 *
 * <p>与 docs/plan-schema.json 中的 operation 判别联合一一对应。</p>
 */
public enum OperationType {

    /** 变速 */
    SPEED("speed"),
    /** 裁切 */
    CROP("crop"),
    /** 字幕 */
    SUBTITLE("subtitle"),
    /** 音量 */
    VOLUME("volume"),
    /** 静音 */
    MUTE("mute"),
    ;

    private final String code;

    OperationType(String code) {
        this.code = code;
    }

    public String getCode() {
        return code;
    }

    public static OperationType fromCode(String code) {
        for (OperationType type : values()) {
            if (type.code.equalsIgnoreCase(code)) {
                return type;
            }
        }
        throw new IllegalArgumentException("未知的剪辑操作类型: " + code);
    }
}
