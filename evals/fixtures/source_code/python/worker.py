"""Background worker with retry logic."""
import time
import logging
from queue import Queue
from threading import Thread
from typing import Callable, Any

logger = logging.getLogger(__name__)

class Task:
    def __init__(self, func: Callable, *args, **kwargs):
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.retries = 0
        self.max_retries = 3
        self.result: Any = None
        self.error: Exception | None = None

class WorkerPool:
    def __init__(self, num_workers: int = 4):
        self.queue: Queue[Task] = Queue()
        self.workers: list[Thread] = []
        self.running = False
        for _ in range(num_workers):
            t = Thread(target=self._worker_loop, daemon=True)
            self.workers.append(t)

    def start(self):
        self.running = True
        for w in self.workers:
            w.start()

    def stop(self):
        self.running = False

    def submit(self, task: Task) -> None:
        self.queue.put(task)

    def _worker_loop(self):
        while self.running:
            try:
                task = self.queue.get(timeout=1)
                self._execute(task)
            except Exception:
                pass

    def _execute(self, task: Task):
        for attempt in range(task.max_retries):
            try:
                task.result = task.func(*task.args, **task.kwargs)
                return
            except Exception as e:
                task.error = e
                task.retries = attempt + 1
                time.sleep(2 ** attempt)
        logger.error(f"Task failed after {task.max_retries} retries")
