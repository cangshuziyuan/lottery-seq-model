import sys
import threading
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.src.analytics import (
    EXPERIMENTS,
    build_backtest,
    build_prediction,
    game_overview,
    prediction_probabilities,
    prediction_record,
    window_stats,
)
from backend.src.config import GAMES
from backend.src.db import (
    cached_report,
    get_meta,
    load_draws,
    load_predictions,
    save_predictions,
    save_report,
)
from backend.src.scraper import fetch_dlt, fetch_ssq
from backend.src.scheduler import DailyScheduler

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
app = Flask(__name__, static_folder=str(FRONTEND), static_url_path="")

FETCHERS = {"ssq": fetch_ssq, "dlt": fetch_dlt}
TICKETS = 5


def _draws(game: str):
    if game not in GAMES:
        return None
    return load_draws(game)


def _signature(draws: list[dict]) -> str:
    latest = draws[-1]
    return f"{len(draws)}:{latest['issue']}:models-v4"


def _report(game: str, kind: str, draws: list[dict], builder):
    signature = _signature(draws)
    cached = cached_report(game, kind, signature)
    if cached:
        return cached
    payload = builder(game, draws)
    save_report(game, kind, signature, payload)
    return payload


def _group_tickets(saved: list[dict]) -> list[dict]:
    grouped = {}
    for row in saved:
        grouped.setdefault(row["model"], []).append(row)
    return [
        {
            "model": model,
            "tickets": [row["ticket"] for row in sorted(grouped[model], key=lambda item: item["created_at"])],
            "source": grouped[model][0]["source"],
            "created_at": grouped[model][0]["created_at"],
        }
        for model in EXPERIMENTS
        if model in grouped
    ]


def _ensure_prediction(game: str, draws: list[dict]) -> dict:
    """下期预测只生成一次并落库；新增模型时只补缺的票，不改已有号码。"""
    latest = draws[-1]
    saved = [row for row in load_predictions(game) if row["based_on"] == latest["issue"]]
    present = {row["model"] for row in saved}
    missing = [model for model in EXPERIMENTS if model not in present]
    if missing:
        built = build_prediction(game, draws, TICKETS)
        save_predictions(
            game,
            built["based_on"],
            built["target_issue"],
            [item for item in built["models"] if item["model"] in missing],
            source="live",
        )
        saved = [row for row in load_predictions(game) if row["based_on"] == latest["issue"]]
    probs = _report(game, "probs", draws, prediction_probabilities)
    return {
        "based_on": latest,
        "target_issue": saved[0]["target_issue"],
        "saved_at": saved[0]["created_at"],
        "source": saved[0]["source"],
        "models": _group_tickets(saved),
        "probabilities": probs["probabilities"],
        "catalog": probs["catalog"],
    }


def sync_all() -> dict:
    """拉取两个彩种的最新开奖，并在开奖更新后刷新下期预测与回测缓存。"""
    games = {}
    for game, fetcher in FETCHERS.items():
        result = fetcher()
        draws = load_draws(game)
        prediction = _ensure_prediction(game, draws)
        if len(draws) >= 220:
            _report(game, "backtest", draws, build_backtest)
        games[game] = {
            "fetched": result["fetched"],
            "filled": result.get("filled", 0),
            "changed": result["changed"],
            "latest": draws[-1]["issue"] if draws else None,
            "target_issue": prediction["target_issue"],
        }
    return {"games": games}


def warm_cache() -> None:
    """启动后预计算，避免访客第一次打开页面时现算。"""
    for game in GAMES:
        draws = load_draws(game)
        if len(draws) < 220:
            continue
        _report(game, "probs", draws, prediction_probabilities)
        _report(game, "backtest", draws, build_backtest)


scheduler = DailyScheduler(sync_all, hour=3, minute=0)


@app.get("/api/overview")
def overview():
    payload = []
    for game in GAMES:
        draws = load_draws(game)
        item = game_overview(game, draws)
        item["fetched_at"] = get_meta(f"{game}_fetched_at")
        payload.append(item)
    return jsonify(payload)


@app.get("/api/schedule")
def schedule_status():
    return jsonify(scheduler.status())


@app.post("/api/schedule/run")
def schedule_run():
    return jsonify(scheduler.run_now())


@app.get("/api/<game>/history")
def history(game: str):
    draws = _draws(game)
    if draws is None:
        return jsonify({"error": "unknown game"}), 404
    limit = max(30, min(request.args.get("limit", 240, type=int), 500))
    return jsonify(draws[-limit:])


@app.get("/api/<game>/stats")
def stats(game: str):
    draws = _draws(game)
    if draws is None:
        return jsonify({"error": "unknown game"}), 404
    return jsonify(window_stats(game, draws))


@app.get("/api/<game>/backtest")
def backtest(game: str):
    draws = _draws(game)
    if draws is None:
        return jsonify({"error": "unknown game"}), 404
    if len(draws) < 220:
        return jsonify({"error": "history is not ready", "count": len(draws)}), 409
    return jsonify(_report(game, "backtest", draws, build_backtest))


@app.get("/api/<game>/predict")
def predict(game: str):
    draws = _draws(game)
    if draws is None:
        return jsonify({"error": "unknown game"}), 404
    if len(draws) < 30:
        return jsonify({"error": "history is not ready"}), 409
    return jsonify(_ensure_prediction(game, draws))


@app.get("/api/<game>/record")
def record(game: str):
    draws = _draws(game)
    if draws is None:
        return jsonify({"error": "unknown game"}), 404
    return jsonify(prediction_record(game, draws, load_predictions(game)))


@app.post("/api/sync/<game>")
def sync(game: str):
    if game not in FETCHERS:
        return jsonify({"error": "unknown game"}), 404
    result = FETCHERS[game]()
    draws = load_draws(game)
    if len(draws) >= 220:
        _report(game, "backtest", draws, build_backtest)
    _ensure_prediction(game, draws)
    return jsonify({"game": result["game"], "fetched": result["fetched"], "changed": result["changed"]})


@app.get("/")
def index():
    return send_from_directory(FRONTEND, "index.html")


if __name__ == "__main__":
    threading.Thread(target=warm_cache, daemon=True, name="lottery-warm").start()
    scheduler.start()
    app.run(host="0.0.0.0", port=5179, debug=False)
