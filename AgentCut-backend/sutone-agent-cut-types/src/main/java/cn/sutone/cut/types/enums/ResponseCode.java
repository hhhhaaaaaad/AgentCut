package cn.sutone.cut.types.enums;

import lombok.Getter;

/**
 * 统一响应码。
 *
 * <p>骨架阶段仅定义基础码，业务码由后续 worker 按需补充。</p>
 */
@Getter
public enum ResponseCode {

    /** 成功 */
    SUCCESS(0, "成功"),
    /** 参数错误 */
    PARAM_ERROR(400, "参数错误"),
    /** 未认证 */
    UNAUTHORIZED(401, "未认证"),
    /** 无权限 */
    FORBIDDEN(403, "无权限"),
    /** 资源不存在 */
    NOT_FOUND(404, "资源不存在"),
    /** 系统内部错误 */
    SYSTEM_ERROR(500, "系统内部错误"),
    ;

    private final int code;
    private final String message;

    ResponseCode(int code, String message) {
        this.code = code;
        this.message = message;
    }
}
