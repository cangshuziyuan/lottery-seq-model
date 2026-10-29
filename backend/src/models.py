from __future__ import annotations

import math
import random
from itertools import combinations

from .config import GAMES, MODELS


def zone_map(game: str) -> dict:
    return {zone["key"]: zone for zone in GAMES[game]["zones"]}


def prize_for(game: str, hits: tuple[int, int]) -> tuple[str, int]:
    for required, label, amount in GAMES[game]["prizes"]:
        if hits == required:
            return label, amount
    return "未中奖", 0


def score_ticket(game: str, ticket: dict, actual: dict) -> dict:
    keys = [zone["key"] for zone in GAMES[game]["zones"]]
    hits = tuple(len(set(ticket[key]) & set(actual[key])) for key in keys)
    label, amount = prize_for(game, hits)
    return {"hits": list(hits), "prize": label, "amount": amount}


def marginals(game: str, history: list[dict], model: str) -> dict[str, dict[int, float]]:
    if model == "ensemble":
        parts = [
            marginals(game, history, key)
            for key, _, _ in MODELS
            if key not in {"ensemble", "uniform_theory", "random"}
        ]
        return _average(parts)
    if model in {"random", "uniform_theory"}:
        return _uniform(game)
    if model == "frequency":
        return _frequency(game, history[-300:])
    if model == "gap":
        return _gap(game, history)
    if model == "markov":
        return _markov(game, history[-500:])
    if model == "cooccur":
        return _cooccur(game, history[-400:])
    if model == "pattern":
        return _pattern(game, history[-180:])
    if model == "recency":
        return _recency(game, history)
    if model == "ewma":
        return _ewma(game, history[-500:])
    if model == "position":
        return _position(game, history[-400:])
    if model == "repeat":
        return _repeat(game, history[-500:])
    if model == "decay":
        return _decay(game, history)
    if model == "overdue":
        return _overdue(game, history)
    if model == "antimarkov":
        return _antimarkov(game, history[-500:])
    if model == "neighbor":
        return _neighbor(game, history)
    raise KeyError(model)


def all_marginals(game: str, history: list[dict]) -> dict[str, dict[str, dict[int, float]]]:
    """一次算出全部模型。ensemble 复用其它模型的结果，避免重复计算。"""
    parts = {
        key: marginals(game, history, key)
        for key, _, _ in MODELS
        if key not in {"ensemble", "uniform_theory"}
    }
    result = dict(parts)
    result["ensemble"] = _average([
        parts[key]
        for key, _, _ in MODELS
        if key not in {"ensemble", "uniform_theory", "random"}
    ])
    result["uniform_theory"] = _uniform(game)
    return result


def predict_ticket(game: str, history: list[dict], model: str, rng: random.Random, temperature: float = 1.0) -> dict:
    return predict_from_weights(game, marginals(game, history, model), rng, temperature)


def predict_from_weights(game: str, weights: dict[str, dict[int, float]], rng: random.Random, temperature: float = 1.0) -> dict:
    """同一份权重下连出多注时复用计算结果。"""
    return {
        zone["key"]: _sample_without_replacement(weights[zone["key"]], zone["count"], rng, temperature)
        for zone in GAMES[game]["zones"]
    }


def model_catalog() -> list[dict]:
    return [{"id": key, "name": name, "idea": idea} for key, name, idea in MODELS]


def _uniform(game: str) -> dict[str, dict[int, float]]:
    result = {}
    for zone in GAMES[game]["zones"]:
        span = zone["max"] - zone["min"] + 1
        result[zone["key"]] = {n: 1 / span for n in range(zone["min"], zone["max"] + 1)}
    return result


def _frequency(game: str, history: list[dict]) -> dict[str, dict[int, float]]:
    result = {}
    draws = max(1, len(history))
    for zone in GAMES[game]["zones"]:
        counts = {n: 1.0 for n in range(zone["min"], zone["max"] + 1)}
        for draw in history:
            for number in draw["numbers"][zone["key"]]:
                counts[number] += 1
        result[zone["key"]] = _normalize(counts, draws)
    return result


def _gap(game: str, history: list[dict]) -> dict[str, dict[int, float]]:
    result = {}
    for zone in GAMES[game]["zones"]:
        gaps = {n: [] for n in range(zone["min"], zone["max"] + 1)}
        last = {n: None for n in gaps}
        for index, draw in enumerate(history):
            for number in draw["numbers"][zone["key"]]:
                if last[number] is not None:
                    gaps[number].append(index - last[number])
                last[number] = index
        weights = {}
        end = len(history) - 1
        for number, values in gaps.items():
            current = end - (last[number] if last[number] is not None else -1)
            mean = sum(values) / len(values) if values else (zone["max"] - zone["min"] + 1) / zone["count"]
            weights[number] = math.exp(-abs(current - mean) / max(mean, 1))
        result[zone["key"]] = _normalize(weights)
    return result


def _markov(game: str, history: list[dict]) -> dict[str, dict[int, float]]:
    result = {}
    if len(history) < 2:
        return _uniform(game)
    previous = history[-1]["numbers"]
    for zone in GAMES[game]["zones"]:
        transition = {
            src: {dst: 0.25 for dst in range(zone["min"], zone["max"] + 1)}
            for src in range(zone["min"], zone["max"] + 1)
        }
        for left, right in zip(history, history[1:]):
            for src in left["numbers"][zone["key"]]:
                for dst in right["numbers"][zone["key"]]:
                    transition[src][dst] += 1
        merged = {n: 0.0 for n in range(zone["min"], zone["max"] + 1)}
        for src in previous[zone["key"]]:
            for dst, value in transition[src].items():
                merged[dst] += value
        result[zone["key"]] = _normalize(merged)
    return result


def _cooccur(game: str, history: list[dict]) -> dict[str, dict[int, float]]:
    result = {}
    if not history:
        return _uniform(game)
    anchor = history[-1]["numbers"]
    for zone in GAMES[game]["zones"]:
        pair = {
            (a, b): 0.2
            for a, b in combinations(range(zone["min"], zone["max"] + 1), 2)
        }
        single = {n: 1.0 for n in range(zone["min"], zone["max"] + 1)}
        for draw in history[:-1]:
            values = draw["numbers"][zone["key"]]
            for number in values:
                single[number] += 1
            for a, b in combinations(sorted(values), 2):
                pair[(a, b)] += 1
        merged = {}
        anchors = anchor[zone["key"]]
        for number in single:
            linked = 0.0
            for other in anchors:
                if other == number:
                    continue
                key = tuple(sorted((other, number)))
                linked += pair[key] / max(single[other], 1)
            merged[number] = 0.35 + linked
        result[zone["key"]] = _normalize(merged)
    return result


def _pattern(game: str, history: list[dict]) -> dict[str, dict[int, float]]:
    base = _frequency(game, history[-80:] or history)
    if len(history) < 20:
        return base
    result = {}
    recent = history[-30:]
    for zone in GAMES[game]["zones"]:
        span = zone["max"] - zone["min"] + 1
        target_sum = sum(sum(draw["numbers"][zone["key"]]) for draw in recent) / len(recent)
        target_odd = sum(sum(n % 2 for n in draw["numbers"][zone["key"]]) for draw in recent) / len(recent)
        cuts = [zone["min"] + span // 3, zone["min"] + 2 * span // 3]
        target_bands = [0, 0, 0]
        for draw in recent:
            bands = [0, 0, 0]
            for number in draw["numbers"][zone["key"]]:
                bands[0 if number < cuts[0] else 1 if number < cuts[1] else 2] += 1
            target_bands = [a + b for a, b in zip(target_bands, bands)]
        target_bands = [value / len(recent) for value in target_bands]
        weights = {}
        for number, prior in base[zone["key"]].items():
            band = 0 if number < cuts[0] else 1 if number < cuts[1] else 2
            odd_bonus = 1 + 0.12 * (1 if target_odd >= zone["count"] / 2 else -1) * (1 if number % 2 else -1)
            center_bonus = math.exp(-abs(number * zone["count"] - target_sum) / span)
            weights[number] = prior * (0.75 + 0.45 * target_bands[band]) * odd_bonus * (0.85 + 0.3 * center_bonus)
        result[zone["key"]] = _normalize(weights)
    return result


def _recency(game: str, history: list[dict]) -> dict[str, dict[int, float]]:
    short = _frequency(game, history[-30:])
    long = _frequency(game, history[-300:] or history)
    result = {}
    for zone in GAMES[game]["zones"]:
        raw = {
            number: max(0.02, short[zone["key"]][number] / max(long[zone["key"]][number], 1e-9))
            for number in short[zone["key"]]
        }
        result[zone["key"]] = _normalize(raw)
    return result


def _ewma(game: str, history: list[dict]) -> dict[str, dict[int, float]]:
    result = {}
    for zone in GAMES[game]["zones"]:
        weights = {number: 1.0 for number in range(zone["min"], zone["max"] + 1)}
        decay = 0.985
        factor = decay ** (len(history) - 1) if history else 1
        for draw in history:
            seen = set(draw["numbers"][zone["key"]])
            for number in weights:
                if number in seen:
                    weights[number] += factor
            factor /= decay
        result[zone["key"]] = _normalize(weights)
    return result


def _position(game: str, history: list[dict]) -> dict[str, dict[int, float]]:
    result = {}
    for zone in GAMES[game]["zones"]:
        counts = {
            slot: {number: 0.25 for number in range(zone["min"], zone["max"] + 1)}
            for slot in range(zone["count"])
        }
        for draw in history:
            for slot, number in enumerate(sorted(draw["numbers"][zone["key"]])):
                counts[slot][number] += 1
        merged = {number: 0.0 for number in range(zone["min"], zone["max"] + 1)}
        for slot in counts.values():
            for number, value in slot.items():
                merged[number] += value
        result[zone["key"]] = _normalize(merged)
    return result


def _repeat(game: str, history: list[dict]) -> dict[str, dict[int, float]]:
    result = {}
    if len(history) < 2:
        return _uniform(game)
    for zone in GAMES[game]["zones"]:
        delays = {number: [] for number in range(zone["min"], zone["max"] + 1)}
        previous = {}
        for index, draw in enumerate(history):
            seen = set(draw["numbers"][zone["key"]])
            for number in seen:
                if number in previous:
                    delays[number].append(index - previous[number])
                previous[number] = index
        weights = {}
        end = len(history) - 1
        for number, values in delays.items():
            current = end - previous.get(number, end)
            target = sum(values) / len(values) if values else (zone["max"] - zone["min"] + 1) / zone["count"]
            weights[number] = math.exp(-((current - target) ** 2) / (2 * max(target, 1) ** 2))
        result[zone["key"]] = _normalize(weights)
    return result


def _decay(game: str, history: list[dict]) -> dict[str, dict[int, float]]:
    """冷号降权：遗漏越长，权重按指数下降。"""
    result = {}
    for zone in GAMES[game]["zones"]:
        last = {number: None for number in range(zone["min"], zone["max"] + 1)}
        for index, draw in enumerate(history):
            for number in draw["numbers"][zone["key"]]:
                last[number] = index
        end = len(history) - 1
        span = zone["max"] - zone["min"] + 1
        typical = span / zone["count"]
        weights = {
            number: math.exp(-((end - seen) if seen is not None else len(history)) / max(typical, 1))
            for number, seen in last.items()
        }
        result[zone["key"]] = _normalize(weights)
    return result


def _overdue(game: str, history: list[dict]) -> dict[str, dict[int, float]]:
    """超期加权：当前遗漏超过该号自己的平均间隔时才加分。"""
    result = {}
    for zone in GAMES[game]["zones"]:
        gaps = {number: [] for number in range(zone["min"], zone["max"] + 1)}
        last = {number: None for number in gaps}
        for index, draw in enumerate(history):
            for number in draw["numbers"][zone["key"]]:
                if last[number] is not None:
                    gaps[number].append(index - last[number])
                last[number] = index
        end = len(history) - 1
        span = zone["max"] - zone["min"] + 1
        weights = {}
        for number, values in gaps.items():
            current = end - (last[number] if last[number] is not None else -1)
            mean = sum(values) / len(values) if values else span / zone["count"]
            ratio = current / max(mean, 1)
            weights[number] = 1 + max(0.0, ratio - 1)
        result[zone["key"]] = _normalize(weights)
    return result


def _antimarkov(game: str, history: list[dict]) -> dict[str, dict[int, float]]:
    """反转：上期号码历史上很少接着出现的号，权重反而更高。"""
    forward = _markov(game, history)
    result = {}
    for zone, table in forward.items():
        ceiling = max(table.values()) + 1e-9
        result[zone] = _normalize({number: ceiling - value for number, value in table.items()})
    return result


def _neighbor(game: str, history: list[dict]) -> dict[str, dict[int, float]]:
    """邻号：上期开出的号，以及它左右相邻的号，下一期权重更高。"""
    result = {}
    if not history:
        return _uniform(game)
    previous = history[-1]["numbers"]
    for zone in GAMES[game]["zones"]:
        weights = {number: 1.0 for number in range(zone["min"], zone["max"] + 1)}
        for number in previous[zone["key"]]:
            for shift, bonus in ((-1, 2.2), (0, 1.4), (1, 2.2)):
                neighbor = number + shift
                if neighbor in weights:
                    weights[neighbor] += bonus
        result[zone["key"]] = _normalize(weights)
    return result


def _average(items: list[dict]) -> dict:
    result = {}
    for zone in items[0]:
        merged = {}
        for number in items[0][zone]:
            merged[number] = sum(item[zone][number] for item in items) / len(items)
        result[zone] = _normalize(merged)
    return result


def _normalize(weights: dict[int, float], _unused: float | None = None) -> dict[int, float]:
    total = sum(max(0.0, value) for value in weights.values()) or 1
    return {key: max(0.0, value) / total for key, value in weights.items()}


def _sample_without_replacement(weights: dict[int, float], count: int, rng: random.Random, temperature: float) -> list[int]:
    keys = list(weights)
    adjusted = [max(weights[key], 1e-12) ** (1 / temperature) for key in keys]
    order = sorted(range(len(keys)), key=lambda index: rng.random() ** (1 / adjusted[index]))
    return sorted(keys[index] for index in order[:count])
