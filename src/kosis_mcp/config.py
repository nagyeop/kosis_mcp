"""Configuration — KOSIS OpenAPI + cache."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

KOSIS_BASE_URL = "https://kosis.kr/openapi"
KOSIS_ENDPOINTS = {
    "statistics_list": "/statisticsList.do",
    "statistics_data": "/statisticsData.do",
    "parameter_data": "/Param/statisticsParameterData.do",
    "search_statistics": "/statisticsSearch.do",
    "stats_explain": "/statisticsExplData.do",
}

VIEW_CODES = {
    "MT_ZTITLE": "국내통계 주제별",
    "MT_OTITLE": "국내통계 기관별",
    "MT_GTITLE01": "e-지방지표(주제별)",
    "MT_GTITLE02": "e-지방지표(지역별)",
    "MT_CHOSUN_TITLE": "광복이전통계(1908~1943)",
    "MT_HANKUK_TITLE": "대한민국통계연감",
    "MT_STOP_TITLE": "작성중지통계",
    "MT_RTITLE": "국제통계",
    "MT_BUKHAN": "북한통계",
    "MT_TM1_TITLE": "대상별통계",
    "MT_TM2_TITLE": "이슈별통계",
    "MT_ETITLE": "영문 KOSIS",
}

PERIOD_CODES = {
    "D": "일",
    "M": "월",
    "Q": "분기",
    "H": "반기",
    "Y": "년",
    "F": "다년(2년~10년)",
    "IR": "부정기",
}

SERVER_VERSION = "2.0.0"
TOOL_COUNT = 14


def get_api_key() -> str:
    return os.environ.get("KOSIS_API_KEY", "")


def cache_ttl_hours() -> int:
    return int(os.environ.get("CACHE_TTL_HOURS", "6"))


def cache_max_keys() -> int:
    return 1000


def redis_url() -> str | None:
    return os.environ.get("REDIS_URL") or None


def validate_config() -> None:
    if not get_api_key():
        raise RuntimeError(
            "KOSIS_API_KEY 환경변수가 설정되지 않았습니다. "
            "https://kosis.kr/openapi/ 에서 무료 발급 후 .env 또는 환경변수로 지정하세요."
        )
