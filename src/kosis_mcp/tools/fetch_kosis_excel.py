"""fetch_kosis_excel — download KOSIS file stats and parse with openpyxl."""

from __future__ import annotations

import asyncio
import io
import re
from datetime import datetime
from typing import Any

import httpx

from kosis_mcp.data.district_file_map import resolve_file_sn_by_keyword
from kosis_mcp.utils.regions import resolve_district_file_table

KOSIS_HOST = "https://stat.kosis.kr"
KOSIS_BASE = f"{KOSIS_HOST}/nsibsHtmlSvc/fileView/FileStbl"


async def _fetch_with_retry(
    client: httpx.AsyncClient, method: str, url: str, **kwargs: Any
) -> httpx.Response:
    last: Exception | None = None
    for i in range(3):
        try:
            return await client.request(method, url, timeout=15.0, **kwargs)
        except Exception as e:
            last = e
            if i < 2:
                await asyncio.sleep(0.8 * (i + 1))
    raise last  # type: ignore[misc]


def _extract_cookies(res: httpx.Response) -> str:
    return "; ".join(f"{k}={v}" for k, v in res.cookies.items())


def _parse_file_list(html: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for m in re.finditer(r"<li\b[^>]*>([\s\S]*?)</li>", html, re.I):
        block = m.group(1)
        sn_m = re.search(r"fn_fileitm_download\s*\(\s*['\"]?(\d+)['\"]?\s*\)", block)
        if not sn_m:
            continue
        sn = int(sn_m.group(1))
        if sn in seen:
            continue
        text = re.sub(r"<script[\s\S]*?</script>", "", block, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        for a, b in (
            ("&nbsp;", " "),
            ("&lt;", "<"),
            ("&gt;", ">"),
            ("&quot;", '"'),
            ("&#39;", "'"),
            ("&amp;", "&"),
        ):
            text = text.replace(a, b)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        seen.add(sn)
        out.append({"file_sn": sn, "file_nm": text[:80] + ("…" if len(text) > 80 else "")})
    if not out:
        for m in re.finditer(r"fn_fileitm_download\s*\(\s*['\"]?(\d+)['\"]?\s*\)", html):
            sn = int(m.group(1))
            if sn in seen:
                continue
            seen.add(sn)
            out.append({"file_sn": sn, "file_nm": f"file_sn={sn}"})
    out.sort(key=lambda x: x["file_sn"])
    return out


def _xlsx_to_markdown(data: bytes) -> str:
    # ponytail: openpyxl markdown; kordoc-level merge HTML if highlight miss rate climbs
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    parts: list[str] = []
    for sheet in wb.worksheets:
        parts.append(f"## {sheet.title}")
        rows_out: list[str] = []
        for row in sheet.iter_rows(values_only=True):
            cells = ["" if c is None else str(c).replace("\n", " ") for c in row]
            if not any(cells):
                continue
            rows_out.append("| " + " | ".join(cells) + " |")
        if rows_out:
            # header separator after first row
            if len(rows_out) >= 1:
                ncols = rows_out[0].count("|") - 1
                sep = "| " + " | ".join(["---"] * max(ncols, 1)) + " |"
                parts.append(rows_out[0])
                parts.append(sep)
                parts.extend(rows_out[1:])
            else:
                parts.extend(rows_out)
        parts.append("")
    wb.close()
    return "\n".join(parts)


async def fetch_kosis_excel(
    districtName: str | None = None,
    year: int | None = None,
    orgId: str | None = None,
    tblId: str | None = None,
    fileSn: int | None = None,
    keyword: str | None = None,
    listOnly: bool = False,
) -> dict[str, Any]:
    org_id = orgId
    tbl_id = tblId
    tbl_candidates: list[str] = []

    if districtName:
        resolved = await resolve_district_file_table(districtName, year)
        if not resolved:
            return {
                "success": False,
                "orgId": org_id or "",
                "tblId": tbl_id or "",
                "error": f'"{districtName}" 자치구 파일통계표를 찾지 못했습니다.',
            }
        org_id = resolved["orgId"]
        tbl_id = resolved["tblId"]
        tbl_candidates = resolved.get("tblIdCandidates") or [tbl_id]
    else:
        if not org_id or not tbl_id:
            return {
                "success": False,
                "orgId": org_id or "",
                "tblId": tbl_id or "",
                "error": "districtName 또는 orgId+tblId가 필요합니다.",
            }
        tbl_candidates = [tbl_id]

    async with httpx.AsyncClient(follow_redirects=True) as client:
        cookie = ""
        html = ""
        used_tbl = tbl_candidates[0]
        last_err = ""
        for cand in tbl_candidates:
            try:
                url = (
                    f"{KOSIS_BASE}/fileStblView.do"
                    f"?in_org_id={org_id}&in_tbl_id={cand}"
                )
                res = await _fetch_with_retry(
                    client,
                    "GET",
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 kosis-mcp",
                        "Accept": "text/html",
                    },
                )
                if res.status_code == 404:
                    last_err = f"HTTP 404 for {cand}"
                    continue
                res.raise_for_status()
                cookie = _extract_cookies(res)
                html = res.text
                used_tbl = cand
                break
            except Exception as e:
                last_err = str(e)
                continue
        else:
            return {
                "success": False,
                "orgId": org_id or "",
                "tblId": tbl_id or "",
                "error": f"파일 통계표 조회 실패: {last_err}",
            }

        files = _parse_file_list(html)
        if listOnly:
            return {
                "success": True,
                "orgId": org_id or "",
                "tblId": used_tbl,
                "files": files,
            }

        effective_sn = fileSn
        if effective_sn is None and keyword:
            effective_sn = resolve_file_sn_by_keyword(files, keyword)
        if effective_sn is None:
            return {
                "success": False,
                "orgId": org_id or "",
                "tblId": used_tbl,
                "files": files,
                "error": "fileSn 또는 keyword로 파일을 지정하세요. listOnly=true로 목록 확인.",
            }

        # download info
        body = {
            "vw_cd": "NULL",
            "list_id": "NULL",
            "org_id": org_id,
            "tbl_id": used_tbl,
            "file_svc": "",
            "file_sn": str(effective_sn),
            "conn_path": "",
        }
        res2 = await _fetch_with_retry(
            client,
            "POST",
            f"{KOSIS_BASE}/fileItmDownload.do",
            data=body,
            headers={
                "User-Agent": "Mozilla/5.0 kosis-mcp",
                "Cookie": cookie,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        res2.raise_for_status()
        j = res2.json()
        rm = j.get("resultMap") or j
        path = rm.get("dwldFilePath")
        name = rm.get("dwldFileNm")
        if not path or not name:
            return {
                "success": False,
                "orgId": org_id or "",
                "tblId": used_tbl,
                "error": f"다운로드 정보 누락: {str(j)[:300]}",
            }

        res3 = await _fetch_with_retry(
            client,
            "POST",
            f"{KOSIS_BASE}/dwldServerFile.do",
            data={
                "org_id": org_id,
                "tbl_id": used_tbl,
                "file_sn": str(effective_sn),
                "img_yn": "",
                "fileSvc": "",
                "file_path": path,
                "file_name": name,
            },
            headers={
                "User-Agent": "Mozilla/5.0 kosis-mcp",
                "Cookie": cookie,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/octet-stream,*/*",
            },
        )
        res3.raise_for_status()
        raw = res3.content
        try:
            md = _xlsx_to_markdown(raw)
        except Exception as e:
            return {
                "success": False,
                "orgId": org_id or "",
                "tblId": used_tbl,
                "error": f"openpyxl 파싱 실패: {e}",
            }
        file_name = next(
            (f["file_nm"] for f in files if f["file_sn"] == effective_sn), None
        )
        return {
            "success": True,
            "orgId": org_id or "",
            "tblId": used_tbl,
            "files": files,
            "fileSn": effective_sn,
            "fileName": file_name,
            "markdown": md,
            "byteSize": len(raw),
        }
