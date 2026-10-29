import math
import random
from collections import Counter
from statistics import mean

from .config import GAMES, MODELS
from .issues import next_issue, parse_issue, yearly_max
from .models import all_marginals, model_catalog, predict_from_weights, score_ticket

EXPERIMENTS = [key for key, _, _ in MODELS if key != "uniform_theory"]
WARMUP = 180
PRIZE_ORDER = ["一等奖", "二等奖", "三等奖", "四等奖", "五等奖", "六等奖", "七等奖", "八等奖", "九等奖"]


def game_overview(game: str, draws: list[dict]) -> dict:
    spec = GAMES[game]
    latest = draws[-1] if draws else None
    return {
        "id": game,
        "name": spec["name"],
        "schedule": spec["schedule"],
        "ticket": spec["ticket"],
        "source": spec["source"],
        "source_url": spec["source_url"],
        "zones": spec["zones"],
        "count": len(draws),
        "latest": latest,
        "first": draws[0] if draws else None,
    }


def window_stats(game: str, draws: list[dict], window: int = 120) -> dict:
    sample = draws[-window:]
    zones = []
    for zone in GAMES[game]["zones"]:
        counter = Counter()
        last = {}
        gaps = []
        sums = []
        for index, draw in enumerate(sample):
            values = draw["numbers"][zone["key"]]
            sums.append(sum(values))
            for number in values:
                if number in last:
                    gaps.append(index - last[number])
                last[number] = index
                counter[number] += 1
        numbers = []
        end = len(sample) - 1
        for number in range(zone["min"], zone["max"] + 1):
            numbers.append(
                {
                    "n": number,
                    "count": counter[number],
                    "gap": end - last[number] if number in last else len(sample),
                }
            )
        numbers.sort(key=lambda item: (-item["count"], item["n"]))
        zones.append(
            {
                **zone,
                "numbers": numbers,
                "avg_sum": round(mean(sums), 1) if sums else 0,
                "avg_gap": round(mean(gaps), 1) if gaps else 0,
            }
        )
    sales = [draw["sales"] for draw in sample if draw.get("sales")]
    return {"window": len(sample), "zones": zones, "avg_sales": round(mean(sales)) if sales else None}


def build_backtest(game: str, draws: list[dict], periods: int | None = None, tickets: int = 5) -> dict:
    start = WARMUP if periods is None else max(WARMUP, len(draws) - periods)
    tested = draws[start:]
    names = {key: name for key, name, _ in MODELS}
    grades = [label for label in PRIZE_ORDER if any(label == prize[1] for prize in GAMES[game]["prizes"])]
    summary = {
        key: {
            "model": key, "name": names[key], "spent": 0, "returned": 0,
            "wins": 0, "best": 0, "prizes": {label: 0 for label in grades},
        }
        for key in EXPERIMENTS
    }
    paired = {key: [] for key in EXPERIMENTS if key != "random"}
    timeline = []
    step = max(1, math.ceil(len(tested) / 240))
    for index, draw in enumerate(tested, start=start):
        history = draws[:index]
        period_return = {}
        point = None
        if (index - start) % step == 0 or index == len(draws) - 1:
            point = {"issue": draw["issue"], "models": {}}
        weights = all_marginals(game, history)
        for model in EXPERIMENTS:
            rng = random.Random(f"{game}:{draw['issue']}:{model}")
            scored = [
                score_ticket(game, predict_from_weights(game, weights[model], rng, 1.15), draw["numbers"])
                for _ in range(tickets)
            ]
            returned = sum(item["amount"] for item in scored)
            item = summary[model]
            item["spent"] += tickets * GAMES[game]["ticket"]
            item["returned"] += returned
            item["wins"] += sum(score["amount"] > 0 for score in scored)
            item["best"] = max(item["best"], max(score["amount"] for score in scored))
            item.setdefault("hit_hist", Counter())
            for score in scored:
                if score["prize"] in item["prizes"]:
                    item["prizes"][score["prize"]] += 1
                item["hit_hist"][sum(score["hits"])] += 1
            period_return[model] = returned
            if point:
                point["models"][model] = item["returned"] - item["spent"]
        for model, values in paired.items():
            values.append(period_return[model] - period_return["random"])
        if point:
            timeline.append(point)
    rows = []
    for model in EXPERIMENTS:
        item = summary[model]
        item["roi"] = round(item["returned"] / item["spent"], 4) if item["spent"] else 0
        item["hit_rate"] = round(item["wins"] / (len(tested) * tickets), 4) if tested else 0
        item["edge"] = item["returned"] - summary["random"]["returned"]
        item["hit_hist"] = {str(hits): count for hits, count in sorted(item.get("hit_hist", {}).items())}
        if model == "random":
            item["interval"] = [0, 0]
            item["separates"] = False
        else:
            item["interval"] = _mean_interval(paired[model])
            item["separates"] = item["interval"][0] > 0 or item["interval"][1] < 0
        rows.append(item)
    return {
        "periods": len(tested),
        "warmup": start,
        "from_issue": tested[0]["issue"] if tested else None,
        "to_issue": tested[-1]["issue"] if tested else None,
        "tickets": tickets,
        "stake": GAMES[game]["ticket"],
        "grades": grades,
        "rows": rows,
        "timeline": timeline,
        "note": "曲线按全历史计算，横轴最多保留 240 个采样点；区间是每期相对随机基线差额的 95% 均值区间。",
    }


def _mean_interval(values: list[int]) -> list[float]:
    count = len(values)
    if count < 2:
        return [0, 0]
    center = sum(values) / count
    variance = sum((value - center) ** 2 for value in values) / (count - 1)
    margin = 1.96 * math.sqrt(variance / count)
    return [round(center - margin, 2), round(center + margin, 2)]


def build_prediction(game: str, draws: list[dict], tickets: int = 5) -> dict:
    """按确定性种子生成下期预测。同一历史 + 同一种子可复现，适合落库留存。"""
    latest = draws[-1]
    result = []
    weights = all_marginals(game, draws)
    for model in EXPERIMENTS:
        rng = random.Random(f"{game}:{latest['issue']}:{model}")
        batch = [predict_from_weights(game, weights[model], rng, 1.05) for _ in range(tickets)]
        result.append({"model": model, "tickets": batch})
    return {
        "based_on": latest["issue"],
        "target_issue": next_issue(latest["issue"], yearly_max(draws, parse_issue(latest["issue"])[0])),
        "models": result,
    }


def prediction_probabilities(game: str, draws: list[dict]) -> dict:
    weights = all_marginals(game, draws)
    probabilities = {
        model: {
            zone: [{"n": n, "p": round(value, 5)} for n, value in sorted(table.items())]
            for zone, table in weights[model].items()
        }
        for model in EXPERIMENTS
    }
    return {"probabilities": probabilities, "catalog": model_catalog()}


def prediction_record(game: str, draws: list[dict], saved: list[dict]) -> dict:
    """把已保存的预测与实际开奖逐注比对。未开奖的期号只列在 pending。"""
    names = {key: name for key, name, _ in MODELS}
    grades = [label for label in PRIZE_ORDER if any(label == prize[1] for prize in GAMES[game]["prizes"])]
    stake = GAMES[game]["ticket"]
    summary = {
        key: {
            "model": key, "name": names[key], "tickets": 0, "spent": 0, "returned": 0,
            "wins": 0, "best": 0, "prizes": {label: 0 for label in grades}, "source": set(),
        }
        for key in EXPERIMENTS
    }
    index = {draw["issue"]: position for position, draw in enumerate(draws)}
    grouped: dict[str, dict[str, list]] = {}
    for row in saved:
        grouped.setdefault(row["based_on"], {}).setdefault(row["model"], []).append(row)

    issues = []
    pending = []
    for based_on in sorted(grouped):
        target_issue = next(iter(grouped[based_on].values()))[0]["target_issue"]
        position = index.get(based_on)
        actual = draws[position + 1] if position is not None and position + 1 < len(draws) else None
        if actual is None:
            pending.append(
                {
                    "based_on": based_on,
                    "target_issue": target_issue,
                    "source": next(iter(grouped[based_on].values()))[0]["source"],
                    "created_at": next(iter(grouped[based_on].values()))[0]["created_at"],
                }
            )
            continue
        point = {
            "based_on": based_on,
            "issue": actual["issue"],
            "date": actual["date"],
            "numbers": actual["numbers"],
            "models": {},
        }
        for model in EXPERIMENTS:
            rows = grouped[based_on].get(model)
            if not rows:
                continue
            scored = [score_ticket(game, row["ticket"], actual["numbers"]) for row in rows]
            item = summary[model]
            returned = sum(score["amount"] for score in scored)
            item["tickets"] += len(scored)
            item["spent"] += len(scored) * stake
            item["returned"] += returned
            item["wins"] += sum(score["amount"] > 0 for score in scored)
            item["best"] = max(item["best"], max(score["amount"] for score in scored))
            for score in scored:
                if score["prize"] in item["prizes"]:
                    item["prizes"][score["prize"]] += 1
                item["source"].add(rows[0]["source"])
            point["models"][model] = {
                "returned": returned,
                "best_hits": max(sum(score["hits"]) for score in scored),
                "cumulative": item["returned"] - item["spent"],
                "tickets": [
                    {"ticket": row["ticket"], "hits": score["hits"], "prize": score["prize"], "amount": score["amount"]}
                    for row, score in zip(rows, scored)
                ],
            }
        issues.append(point)

    rows = []
    for model in EXPERIMENTS:
        item = summary[model]
        item["source"] = ",".join(sorted(item["source"])) or "-"
        item["roi"] = round(item["returned"] / item["spent"], 4) if item["spent"] else 0
        item["hit_rate"] = round(item["wins"] / item["tickets"], 4) if item["tickets"] else 0
        rows.append(item)
    for point in issues[:-20]:
        for item in point["models"].values():
            item.pop("tickets", None)
    return {
        "grades": grades,
        "rows": rows,
        "issues": issues,
        "pending": pending,
        "note": "每行是已保存预测与随后一期实际开奖的逐注比对；逐注明细只保留最近 20 期。金额按公开固定奖级估算，浮动奖用保守常量。",
    }
