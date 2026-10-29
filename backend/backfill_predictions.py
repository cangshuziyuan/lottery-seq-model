"""回填历史预测：用与实盘完全相同的确定性规则补出留存记录，便于立刻看比对结果。

回填行标记为 backfill，且不覆盖任何实盘记录。
"""

import argparse

from backend.src.analytics import EXPERIMENTS, build_prediction
from backend.src.db import load_draws, load_predictions, save_predictions


def backfill(game: str, limit: int) -> dict:
    draws = load_draws(game)
    present = {}
    for row in load_predictions(game):
        present.setdefault(row["based_on"], set()).add(row["model"])
    written = 0
    skipped = 0
    for index in range(max(1, len(draws) - limit - 1), len(draws) - 1):
        based_on = draws[index]["issue"]
        missing = [model for model in EXPERIMENTS if model not in present.get(based_on, set())]
        if not missing:
            skipped += 1
            continue
        built = build_prediction(game, draws[: index + 1])
        written += save_predictions(
            game,
            built["based_on"],
            built["target_issue"],
            [item for item in built["models"] if item["model"] in missing],
            source="backfill",
        )
    return {"game": game, "written": written, "skipped": skipped, "draws": len(draws)}


def main() -> None:
    parser = argparse.ArgumentParser(description="回填已保存预测记录")
    parser.add_argument("--limit", type=int, default=60, help="回填最近多少期，默认 60")
    parser.add_argument("--game", choices=["ssq", "dlt"], help="只回填指定彩种")
    args = parser.parse_args()
    for game in ([args.game] if args.game else ["ssq", "dlt"]):
        print(backfill(game, args.limit))


if __name__ == "__main__":
    main()
