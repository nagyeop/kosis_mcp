"""Tool error helpers."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    INVALID_API_KEY = "INVALID_API_KEY"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    INVALID_PARAMETER = "INVALID_PARAMETER"
    NO_DATA_FOUND = "NO_DATA_FOUND"
    API_UNAVAILABLE = "API_UNAVAILABLE"
    NETWORK_ERROR = "NETWORK_ERROR"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


ERROR_MESSAGES: dict[str, str] = {
    ErrorCode.INVALID_API_KEY: "API 키가 유효하지 않습니다. 환경 설정을 확인해주세요.",
    ErrorCode.RATE_LIMIT_EXCEEDED: "요청 한도를 초과했습니다. 잠시 후 다시 시도해주세요.",
    ErrorCode.INVALID_PARAMETER: "검색 조건이 올바르지 않습니다. 다른 조건으로 시도해주세요.",
    ErrorCode.NO_DATA_FOUND: "해당 조건에 맞는 데이터가 없습니다.",
    ErrorCode.API_UNAVAILABLE: "KOSIS 서비스가 일시적으로 응답하지 않습니다. 잠시 후 다시 시도해주세요.",
    ErrorCode.NETWORK_ERROR: "네트워크 연결을 확인해주세요.",
    ErrorCode.UNKNOWN_ERROR: "알 수 없는 오류가 발생했습니다.",
}


def get_error_message(code: str) -> str:
    return ERROR_MESSAGES.get(code, ERROR_MESSAGES[ErrorCode.UNKNOWN_ERROR])


def handle_tool_error(error: Any) -> dict[str, Any]:
    print(f"Tool error: {error}", flush=True)
    if isinstance(error, Exception):
        code = getattr(error, "code", None)
        if code:
            return {
                "success": False,
                "error": get_error_message(str(code)),
                "code": str(code),
            }
        return {
            "success": False,
            "error": str(error),
            "code": ErrorCode.UNKNOWN_ERROR,
        }
    return {
        "success": False,
        "error": get_error_message(ErrorCode.UNKNOWN_ERROR),
        "code": ErrorCode.UNKNOWN_ERROR,
    }
