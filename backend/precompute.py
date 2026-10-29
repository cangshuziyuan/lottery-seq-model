"""手动预计算：把回测与模型概率写进 reports 缓存，省去首次访问的等待。"""

import time

from backend.src.analytics import build_backtest, prediction_probabilities
from backend.src.db import load_draws, save_report


def main() -> None:
    for game in ("ssq", "dlt"):
        draws = load_draws(game)
        if len(draws) < 220:
            print(game, "历史不足 220 期，跳过")
            continue
        signature = f"{len(draws)}:{draws[-1]['issue']}:models-v4"
        started = time.time()
        report = build_backtest(game, draws)
        save_report(game, "backtest", signature, report)
        print(game, "backtest", round(time.time() - started, 1), report["periods"])
        started = time.time()
        save_report(game, "probs", signature, prediction_probabilities(game, draws))
        print(game, "probs", round(time.time() - started, 1))


if __name__ == "__main__":
    main()
