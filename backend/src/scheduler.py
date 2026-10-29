"""每日定时任务：开奖次日凌晨 3 点拉取开奖结果并刷新下期预测。"""

import threading
from datetime import datetime, timedelta


class DailyScheduler:
    def __init__(self, job, hour: int = 3, minute: int = 0):
        self.job = job
        self.hour = hour
        self.minute = minute
        self.last_run = None
        self.last_result = None
        self.error = None
        self._next = None
        self._stop = threading.Event()
        self._thread = None

    def start(self) -> None:
        if self._thread:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="lottery-scheduler")
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._next = self._next_run()
            self._stop.wait((self._next - datetime.now()).total_seconds())
            if self._stop.is_set():
                break
            self.run_now()

    def run_now(self) -> dict:
        self.last_run = datetime.now()
        try:
            self.last_result = self.job()
            self.error = None
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            self.last_result = None
        return self.status()

    def _next_run(self) -> datetime:
        now = datetime.now()
        target = now.replace(hour=self.hour, minute=self.minute, second=0, microsecond=0)
        return target if target > now else target + timedelta(days=1)

    def status(self) -> dict:
        return {
            "hour": self.hour,
            "minute": self.minute,
            "next_run": self._next.isoformat(timespec="seconds") if self._next else None,
            "last_run": self.last_run.isoformat(timespec="seconds") if self.last_run else None,
            "last_result": self.last_result,
            "error": self.error,
        }
