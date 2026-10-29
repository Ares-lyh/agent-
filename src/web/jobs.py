"""Local workers; authoritative recoverable work always lives in checkpoint.json."""
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock


class StudioJobs:
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="studio")
        self.guard = Lock()
        self.futures: dict[str, Future] = {}

    def submit(self, project_id, prepare, execute):
        with self.guard:
            future = self.futures.get(project_id)
            if future is not None and not future.done():
                return  # Duplicate clicks join the existing transaction.
            prepare()  # Persist intent and validate conflicts before returning HTTP 202.
            self.futures[project_id] = self.executor.submit(execute)

    def status(self, project_id):
        with self.guard:
            future = self.futures.get(project_id)
            if future is None:
                return None
            if not future.done():
                return "running" if future.running() else "queued"
            return "failed" if future.exception() is not None else "idle"


studio_jobs = StudioJobs()
