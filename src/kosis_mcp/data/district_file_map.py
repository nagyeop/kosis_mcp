"""District OpenAPI routes + excel highlight extraction."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, TypedDict

class DistrictOpenApiRoute(TypedDict, total=False):
    orgId: str
    tableId: str
    itemId: str
    objL2: str
    period: str
    unit: str
    description: str
    regionObjLevel: int
    objIdHint: str

_DIR = Path(__file__).resolve().parent
DISTRICT_OPENAPI_ROUTES: dict[str, DistrictOpenApiRoute] = json.loads(
    (_DIR / "_district_openapi_routes.json").read_text(encoding="utf-8")
)
DISTRICT_KEYWORD_TO_FILESN: dict[str, int] = json.loads(
    (_DIR / "_district_keyword_to_filesn.json").read_text(encoding="utf-8")
)

FILESN_BUNYA_PATTERN: dict[int, re.Pattern[str]] = {
    2: re.compile(r"""인구|가구|세대"""),
    3: re.compile(r"""노동|사업체|고용|취업"""),
    7: re.compile(r"""주택|건설|주거"""),
    9: re.compile(r"""보건|의료|위생"""),
}

HIGHLIGHT_PATTERNS: dict[str, re.Pattern[str]] = {
    "인구": re.compile(r"""(?:총|등록|주민등록)?\s*인구(?!\s*동태)|인구밀도"""),
    "총인구": re.compile(r"""총\s*인구|등록\s*인구|주민등록\s*인구"""),
    "고령인구": re.compile(r"""65세\s*이상|고령\s*인구|노인\s*인구"""),
    "노인인구": re.compile(r"""65세\s*이상|고령\s*인구|노인\s*인구"""),
    "65세이상인구": re.compile(r"""65세\s*이상"""),
    "출산율": re.compile(r"""합계\s*출산율|조출생률|출생률"""),
    "합계출산율": re.compile(r"""합계\s*출산율"""),
    "출생아수": re.compile(r"""출생아\s*수|출생자\s*수"""),
    "출생아": re.compile(r"""출생아|출생자"""),
    "조출생률": re.compile(r"""조출생률|출생률"""),
    "사망자수": re.compile(r"""사망자\s*수|사망자"""),
    "사망자": re.compile(r"""사망자"""),
    "조사망률": re.compile(r"""조사망률|사망률"""),
    "사망률": re.compile(r"""사망률"""),
    "혼인율": re.compile(r"""혼인율|조혼인율"""),
    "조혼인율": re.compile(r"""조혼인율"""),
    "혼인건수": re.compile(r"""혼인\s*건수|혼인"""),
    "이혼율": re.compile(r"""이혼율|조이혼율"""),
    "조이혼율": re.compile(r"""조이혼율"""),
    "이혼건수": re.compile(r"""이혼\s*건수|이혼"""),
    "자연증가": re.compile(r"""자연증가"""),
    "자연증가율": re.compile(r"""자연증가율"""),
    "노령화지수": re.compile(r"""노령화\s*지수|고령화\s*지수"""),
    "고령화지수": re.compile(r"""노령화\s*지수|고령화\s*지수"""),
    "초혼연령": re.compile(r"""초혼\s*연령|평균\s*초혼"""),
    "평균초혼연령": re.compile(r"""평균\s*초혼"""),
    "남성초혼연령": re.compile(r"""남(?:자|성)\s*평균?\s*초혼"""),
    "여성초혼연령": re.compile(r"""여(?:자|성)\s*평균?\s*초혼"""),
    "취업자수": re.compile(r"""취업자\s*(?:수)?"""),
    "취업자": re.compile(r"""취업자\s*(?:수)?"""),
    "실업률": re.compile(r"""실업률"""),
    "실업자수": re.compile(r"""실업자\s*(?:수)?"""),
    "실업자": re.compile(r"""실업자\s*(?:수)?"""),
    "고용률": re.compile(r"""고용률"""),
    "경제활동인구": re.compile(r"""경제활동\s*인구(?!\s*비)"""),
    "비경제활동인구": re.compile(r"""비\s*경제활동\s*인구"""),
    "임금": re.compile(r"""(?:월\s*평균|평균)?\s*임금|월\s*급여"""),
    "월평균임금": re.compile(r"""월\s*평균\s*임금"""),
    "월급": re.compile(r"""(?:월\s*평균)?\s*임금|월\s*급여"""),
    "평균임금": re.compile(r"""평균\s*임금"""),
    "주택가격": re.compile(r"""주택\s*(?:매매)?\s*가격|주택매매"""),
    "주택매매가격": re.compile(r"""주택\s*매매"""),
    "주택가격지수": re.compile(r"""주택\s*가격\s*지수|주택매매\s*가격\s*지수"""),
    "아파트가격": re.compile(r"""아파트\s*(?:매매)?\s*가격|아파트매매"""),
    "아파트매매가격": re.compile(r"""아파트\s*매매"""),
    "아파트가격지수": re.compile(r"""아파트\s*가격\s*지수"""),
    "아파트": re.compile(r"""아파트"""),
    "전세가격": re.compile(r"""전세\s*(?:가격)?"""),
    "전세가격지수": re.compile(r"""전세\s*가격\s*지수"""),
    "주택전세": re.compile(r"""(?:주택|아파트)?\s*전세"""),
    "전세": re.compile(r"""전세"""),
    "아파트전세": re.compile(r"""아파트\s*전세"""),
    "아파트전세가격": re.compile(r"""아파트\s*전세"""),
    "의사": re.compile(r"""(?:^|[^원])의사\s*(?:수)?"""),
    "의사수": re.compile(r"""의사\s*수"""),
    "의료인력": re.compile(r"""의료\s*인력|의사\s*수"""),
}

KEYWORD_TO_HEADER_PATTERN: dict[str, re.Pattern[str]] = {
    "인구": re.compile(r"""^등록인구$|^인구$|^총인구$|^주민등록\s*총인구$|^합\s*계$"""),
    "총인구": re.compile(r"""^등록인구$|^인구$|^총인구$"""),
    "고령인구": re.compile(r"""65세\s*이상"""),
    "노인인구": re.compile(r"""65세\s*이상"""),
    "65세이상인구": re.compile(r"""65세\s*이상"""),
    "세대": re.compile(r"""^세\s*대$|^세대수$"""),
    "취업자수": re.compile(r"""^취업자(?:\s*수)?$"""),
    "취업자": re.compile(r"""^취업자(?:\s*수)?$"""),
    "실업률": re.compile(r"""^실업률$"""),
    "고용률": re.compile(r"""^고용률$"""),
    "의사": re.compile(r"""^의\s*사(?:\s*수)?$"""),
    "의사수": re.compile(r"""^의\s*사\s*수$"""),
}

NUMBER_WITH_UNIT_RX = re.compile(
    r"([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{5,})\s*(?:명\s*/\s*km²|명|세대|호|개소|개|%|m²|km²|건|대|원|만원|점|위|년|세)"
)
NUMBER_BARE_RX = re.compile(r"(?<![0-9.,])([0-9]{1,3}(?:,[0-9]{3})+)(?![0-9.,])")


def resolve_file_sn_by_keyword(files: list[dict[str, Any]], keyword: str) -> int | None:
    static_sn = DISTRICT_KEYWORD_TO_FILESN.get(keyword)
    if static_sn is None:
        return None
    pattern = FILESN_BUNYA_PATTERN.get(static_sn)
    if not pattern:
        return None
    matched = next((f for f in files if pattern.search(str(f.get("file_nm", "")))), None)
    return int(matched["file_sn"]) if matched else None


def clean_cell_text(raw: str) -> str:
    s = re.sub(r"<br\s*/?>", " ", raw, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    return re.sub(r"\s+", " ", s).strip()


def build_grid(table_html: str) -> list[list[str]]:
    tr_matches = re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", table_html, flags=re.I)
    grid: list[list[str]] = []
    carry_down: dict[int, dict[str, Any]] = {}
    for tr in tr_matches:
        cells = re.findall(r"<(t[hd])([^>]*)>([\s\S]*?)</\1>", tr, flags=re.I)
        row: list[str] = []
        col = 0

        def consume_carry() -> None:
            nonlocal col
            while col in carry_down:
                carry = carry_down[col]
                while len(row) <= col:
                    row.append("")
                row[col] = carry["text"]
                carry["remaining"] -= 1
                if carry["remaining"] == 0:
                    del carry_down[col]
                col += 1

        for _tag, attrs, text_raw in cells:
            consume_carry()
            text = clean_cell_text(text_raw)
            cs_m = re.search(r'colspan\s*=\s*"?(\d+)"?', attrs, re.I)
            rs_m = re.search(r'rowspan\s*=\s*"?(\d+)"?', attrs, re.I)
            cs = int(cs_m.group(1)) if cs_m else 1
            rs = int(rs_m.group(1)) if rs_m else 1
            for c in range(cs):
                while len(row) <= col + c:
                    row.append("")
                row[col + c] = text
                if rs > 1:
                    carry_down[col + c] = {"text": text, "remaining": rs - 1}
            col += cs
        consume_carry()
        grid.append(row)
    return grid


def split_grid(grid: list[list[str]]) -> tuple[list[list[str]], list[list[str]]]:
    year_rx = re.compile(r"^(?:19|20)\d{2}$")
    header_rows: list[list[str]] = []
    data_rows: list[list[str]] = []
    for row in grid:
        is_data = (
            (len(row) > 0 and row[0] and year_rx.match(row[0]))
            or (len(row) > 1 and row[1] and year_rx.match(row[1]))
            or (len(row) > 1 and row[0] == "" and row[1] and year_rx.match(row[1]))
        )
        (data_rows if is_data else header_rows).append(row)
    return header_rows, data_rows


def parse_cell_value(cell: str) -> dict[str, str | None]:
    if not cell:
        return {"value": None, "unit": None}
    with_unit = NUMBER_WITH_UNIT_RX.search(cell)
    if with_unit:
        after = cell[with_unit.start(1) + len(with_unit.group(1)) :]
        u = re.match(r"^\s*(명\s*/\s*km²|명|세대|호|개소|개|%|m²|km²|건|대|원|만원|점|위|년|세)", after)
        return {
            "value": with_unit.group(1),
            "unit": re.sub(r"\s+", "", u.group(1)) if u else None,
        }
    bare = re.match(r"^-?[0-9]{1,3}(?:,[0-9]{3})+$|^-?[0-9]{4,}$|^-?[0-9]+(?:\.[0-9]+)?$", cell)
    if bare:
        n = float(bare.group(0).replace(",", ""))
        if not (n == int(n) and 1900 <= n <= 2099 and "," not in cell):
            return {"value": bare.group(0), "unit": None}
    return {"value": None, "unit": None}


def find_keyword_column(header_rows: list[list[str]], header_pattern: re.Pattern[str]) -> int:
    for row in header_rows:
        for c, cell in enumerate(row):
            if cell and header_pattern.search(cell):
                return c
    return -1


def extract_from_html_table(markdown: str, keyword: str) -> dict[str, Any]:
    table_blocks = re.findall(r"<table>[\s\S]*?</table>", markdown, flags=re.I)
    if not table_blocks:
        return {"value": None, "unit": None, "contextRows": []}
    keyword_snippet = HIGHLIGHT_PATTERNS.get(keyword) or re.compile(re.escape(keyword))
    header_pattern = KEYWORD_TO_HEADER_PATTERN.get(keyword)
    data_row_rx = re.compile(r"<t[hd][^>]*>\s*(?:19|20)\d{2}\s*</t[hd]>", re.I)
    candidates = [t for t in table_blocks if keyword_snippet.search(t) and data_row_rx.search(t)]
    fallback = next((t for t in table_blocks if data_row_rx.search(t)), None)
    target_table = candidates[0] if candidates else fallback
    if not target_table:
        return {"value": None, "unit": None, "contextRows": []}
    grid = build_grid(target_table)
    header_rows, data_rows = split_grid(grid)
    if not data_rows:
        return {"value": None, "unit": None, "contextRows": []}

    def year_of(row: list[str]) -> int:
        y = row[0] if row and re.match(r"^(?:19|20)\d{2}$", row[0] or "") else (row[1] if len(row) > 1 else "0")
        try:
            return int(y)
        except ValueError:
            return 0

    sorted_data = sorted(data_rows, key=year_of, reverse=True)
    latest = sorted_data[0]
    latest_year = str(year_of(latest))
    header_joined = [" | ".join(c for c in r if c) for r in header_rows[:5]]
    header_joined = [s for s in header_joined if s]
    data_joined = [f"[{year_of(r)}] " + " | ".join(c for c in r[1:] if c) for r in sorted_data[:5]]
    context_rows = header_joined + data_joined
    value = None
    unit = None
    if header_pattern:
        col = find_keyword_column(header_rows, header_pattern)
        if 0 <= col < len(latest):
            parsed = parse_cell_value(latest[col])
            if parsed["value"]:
                value, unit = parsed["value"], parsed["unit"]
    if not value and keyword in ("인구", "총인구"):
        max_num = 0.0
        max_str = None
        for td in latest[1:]:
            parsed = parse_cell_value(td)
            if not parsed["value"]:
                continue
            n = float(str(parsed["value"]).replace(",", ""))
            if n > max_num and n > 1000:
                max_num = n
                max_str = parsed["value"]
        if max_str:
            value, unit = max_str, "명"
    if value and not unit:
        if keyword in ("인구", "총인구", "고령인구", "노인인구", "65세이상인구"):
            unit = "명"
        elif keyword == "세대":
            unit = "세대"
        elif keyword in ("실업률", "고용률"):
            unit = "%"
    if value:
        context_rows.insert(0, f"(최신 {latest_year}년 데이터)")
    return {"value": value, "unit": unit, "contextRows": context_rows}


def extract_district_highlight(markdown: str, keyword: str) -> dict[str, Any]:
    if re.search(r"<table>", markdown, re.I):
        html = extract_from_html_table(markdown, keyword)
        if html["value"]:
            return {"value": html["value"], "unit": html["unit"], "highlightLines": html["contextRows"]}
        if html["contextRows"]:
            return {"value": None, "unit": None, "highlightLines": html["contextRows"]}
    pattern = HIGHLIGHT_PATTERNS.get(keyword)
    if not pattern:
        return {"value": None, "unit": None, "highlightLines": []}
    lines = markdown.split("\n")
    highlight_lines: list[str] = []
    included: set[int] = set()
    for i, line in enumerate(lines):
        if not pattern.search(line):
            continue
        start = max(0, i - 1)
        end = min(len(lines), i + 3)
        for j in range(start, end):
            if j in included:
                continue
            included.add(j)
            highlight_lines.append(lines[j])
        if len(highlight_lines) >= 50:
            break
    value = None
    unit = None
    for line in highlight_lines:
        with_unit = NUMBER_WITH_UNIT_RX.search(line)
        if with_unit:
            value = with_unit.group(1)
            after = line[with_unit.start(1) + len(with_unit.group(1)) :]
            u = re.match(r"^\s*(명\s*/\s*km²|명|세대|호|개소|개|%|m²|km²|건|대|원|만원|점|위|년|세)", after)
            unit = re.sub(r"\s+", "", u.group(1)) if u else None
            break
        bare = NUMBER_BARE_RX.search(line)
        if bare and not value:
            num = int(bare.group(1).replace(",", ""))
            if num >= 1000 and (num < 1900 or num > 2100):
                value = bare.group(1)
    return {"value": value, "unit": unit, "highlightLines": highlight_lines}
