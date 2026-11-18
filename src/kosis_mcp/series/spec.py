"""spec — 분석 대상 계열 지정 (find_tables tables[i]의 orgId·tableId를 그대로 받는다)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field
from typing_extensions import Required, TypedDict

PeriodType = Literal["Y", "H", "Q", "M", "D", "IR", "F"]
RegionLevel = Literal["sido", "sigungu"]


class SeriesSpec(TypedDict, total=False):
    orgId: Required[Annotated[str, Field(description="기관 ID (find_tables tables[i].orgId)")]]
    tableId: Required[Annotated[str, Field(description="통계표 ID (find_tables tables[i].tableId)")]]
    item: Annotated[
        str | list[str],
        Field(description='항목 이름 또는 ITM_ID. 여러 개면 리스트, 전체는 "ALL". 생략하면 첫 항목(appliedDefaults로 보고)'),
    ]
    regions: Annotated[
        list[str] | Literal["ALL"],
        Field(
            description='지역 이름 리스트. 동명 지역은 상위 지역을 붙인다("부산 중구", "서울 강남구 신사동"). '
            '"전국"은 합계 행. 전체는 "ALL"(level과 함께 권장)'
        ),
    ]
    level: Annotated[RegionLevel, Field(description='regions="ALL"일 때 남길 행정 수준. 생략하면 모든 수준')]
    filters: Annotated[
        dict[str, str],
        Field(
            description='지역·항목 외 분류 {분류명: 값 이름 | "ALL"}. 예: {"성별": "여자", "5세별": "65 - 69세"}. '
            "분류명·값은 get_table_info로 확인. 생략한 분류는 합계(계) 또는 첫 값"
        ),
    ]
    codes: Annotated[
        dict[str, str],
        Field(description="코드 직접 지정 {objL1..objL8, itmId}. 지정한 키는 이름 매칭보다 우선"),
    ]
    periodType: Annotated[
        PeriodType,
        Field(description="수록 주기 Y|H|Q|M|D|IR|F. 생략하면 analyze_trend는 Y 우선, compare_values는 가장 촘촘한 주기"),
    ]
    label: Annotated[str, Field(description="결과 열·계열 이름(기본 s1, s2…). derive 수식에서 이 이름을 쓴다")]


class DeriveSpec(TypedDict, total=False):
    name: Required[Annotated[str, Field(description="파생 지표 이름 (결과 rows[].derived의 키)")]]
    expr: Required[
        Annotated[
            str,
            Field(description='사칙연산 수식. 이름은 열 label(기본 s1, s2…) 또는 열 순번 c1, c2…. 예: "인구 / 세대"'),
        ]
    ]
    unit: Annotated[str, Field(description="결과 단위 라벨. 생략하면 a/b 꼴에서 자동")]


def spec_label(spec: SeriesSpec, index: int) -> str:
    return spec.get("label") or f"s{index + 1}"
