package cn.sutone.cut.types.exception;

import cn.sutone.cut.types.enums.ResponseCode;
import lombok.Getter;

/**
 * 业务异常。业务逻辑层抛出的统一异常，由全局异常处理器转换为统一响应。
 */
@Getter
public class AppException extends RuntimeException {

    private final ResponseCode responseCode;

    public AppException(ResponseCode responseCode) {
        super(responseCode.getMessage());
        this.responseCode = responseCode;
    }

    public AppException(ResponseCode responseCode, String message) {
        super(message);
        this.responseCode = responseCode;
    }

    public AppException(ResponseCode responseCode, Throwable cause) {
        super(responseCode.getMessage(), cause);
        this.responseCode = responseCode;
    }
}
