import time
from datetime import datetime

import requests

from .db import issue_set, set_meta, upsert_draws
from .issues import is_following

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}
SESSION = requests.Session()
SESSION.trust_env = False


def _money(value) -> int | None:
    if value in (None, ""):
        return None
    return int(str(value).replace(",", "").split(".")[0])


def fetch_ssq(page_size: int = 30, pause: float = 0.25) -> dict:
    url = "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice"
    headers = {**HEADERS, "Referer": "https://www.cwl.gov.cn/ygkj/wqkjgg/ssq/"}
    rows, pages = _collect_recent(
        "ssq",
        url,
        headers,
        lambda page, size: _ssq_params(page, size),
        lambda payload: payload.get("result", []),
        _ssq_row,
        page_size,
        pause,
    )
    changed = upsert_draws("ssq", rows)
    set_meta("ssq_fetched_at", datetime.now().isoformat(timespec="seconds"))
    return {"game": "ssq", "fetched": len(rows), "changed": changed, "pages": pages, "filled": max(0, len(rows) - 1)}


def _ssq_params(page: int, size: int) -> dict:
    return {
        "name": "ssq",
        "issueCount": "",
        "issueStart": "",
        "issueEnd": "",
        "dayStart": "",
        "dayEnd": "",
        "pageNo": page,
        "pageSize": size,
        "week": "",
        "systemType": "PC",
    }


def fetch_dlt(page_size: int = 30, pause: float = 0.15) -> dict:
    url = "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry"
    headers = {**HEADERS, "Referer": "https://www.sporttery.cn/", "Origin": "https://www.sporttery.cn"}
    rows, pages = _collect_recent(
        "dlt",
        url,
        headers,
        lambda page, size: _dlt_params(page, size),
        lambda payload: payload["value"].get("list", []),
        _dlt_row,
        page_size,
        pause,
    )
    changed = upsert_draws("dlt", rows)
    set_meta("dlt_fetched_at", datetime.now().isoformat(timespec="seconds"))
    return {"game": "dlt", "fetched": len(rows), "changed": changed, "pages": pages, "filled": max(0, len(rows) - 1)}


def _collect_recent(game, url, headers, params, extract, convert, page_size, pause):
    stored = issue_set(game)
    collected = []
    seen = set()
    pages = 0
    while pages < 300:
        pages += 1
        response = SESSION.get(url, params=params(pages, page_size), headers=headers, timeout=30)
        response.raise_for_status()
        page_rows = []
        for item in extract(response.json()):
            row = convert(item)
            if row["issue"] not in seen:
                page_rows.append(row)
                seen.add(row["issue"])
        if not page_rows:
            break
        collected.extend(page_rows)
        ordered = sorted(collected, key=lambda row: row["issue"])
        if pages == 1 and stored and ordered[-1]["issue"] in stored and _contiguous(ordered):
            return [ordered[-1]], pages
        if stored and min(row["issue"] for row in ordered) <= min(stored) and _contiguous(ordered):
            break
        if not stored and pages >= 120:
            break
        time.sleep(pause)
    ordered = sorted(collected, key=lambda row: row["issue"])
    missing = [row for row in ordered if row["issue"] not in stored]
    latest = [ordered[-1]] if ordered else []
    return list({row["issue"]: row for row in missing + latest}.values()), pages


def _contiguous(rows: list[dict]) -> bool:
    issues = [row["issue"] for row in rows]
    for previous, current in zip(issues, issues[1:]):
        if not is_following(previous, current):
            return False
    return True


def _ssq_row(item: dict) -> dict:
    return {
        "issue": item["code"],
        "date": item["date"][:10],
        "numbers": {
            "red": sorted(int(value) for value in item["red"].split(",")),
            "blue": [int(item["blue"])],
        },
        "sales": _money(item.get("sales")),
        "pool": _money(item.get("poolmoney")),
    }


def _dlt_row(item: dict) -> dict:
    values = [int(value) for value in item["lotteryDrawResult"].split()]
    return {
        "issue": item["lotteryDrawNum"],
        "date": item["lotteryDrawTime"][:10],
        "numbers": {"front": sorted(values[:5]), "back": sorted(values[5:])},
        "sales": _money(item.get("totalSaleAmount")),
        "pool": _money(item.get("poolBalanceAfterdraw")),
    }


def _dlt_params(page: int, size: int) -> dict:
    return {
        "gameNo": 85,
        "provinceId": 0,
        "pageSize": size,
        "isVerify": 1,
        "pageNo": page,
    }
