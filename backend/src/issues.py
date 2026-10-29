"""期号算术：兼容 2026123 与早期 07001 两种写法。"""


def parse_issue(issue: str) -> tuple[int, int]:
    if len(issue) >= 7:
        return int(issue[:4]), int(issue[4:])
    return int(issue[:-3]), int(issue[-3:])


def format_issue(year: int, number: int, template: str) -> str:
    if len(template) >= 7:
        return f"{year:04d}{number:0{len(template) - 4}d}"
    return f"{year:02d}{number:03d}"


def is_following(previous: str, current: str) -> bool:
    """current 是否紧跟 previous 的一期。"""
    if current == previous:
        return False
    prev_year, prev_number = parse_issue(previous)
    year, number = parse_issue(current)
    return (year == prev_year and number == prev_number + 1) or (
        year == prev_year + 1 and number == 1
    )


def next_issue(issue: str, yearly_max: int | None = None) -> str:
    """推算下一期号。yearly_max 是上一年最后一期的序号，用于跨年翻页。"""
    year, number = parse_issue(issue)
    if yearly_max is not None and number + 1 > yearly_max:
        return format_issue(year + 1, 1, issue)
    return format_issue(year, number + 1, issue)


def yearly_max(draws: list[dict], year: int) -> int | None:
    """返回上一年最后一期的序号；没有上一年数据时返回 None。"""
    numbers = [
        parse_issue(draw["issue"])[1]
        for draw in draws
        if parse_issue(draw["issue"])[0] == year - 1
    ]
    return max(numbers) if numbers else None
