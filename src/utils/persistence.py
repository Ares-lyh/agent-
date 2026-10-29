"""Atomic writes, exclusive publication, and cross-process project locks."""
import os
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

_locks = {}
_guard = threading.Lock()

def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with open(temporary, "wb") as stream:
            stream.write(content.encode("utf-8") if isinstance(content, str) else content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)

def publish(temporary, destination):
    temporary = Path(temporary)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with open(temporary, "r+b") as stream:
        os.fsync(stream.fileno())
    try:
        os.replace(temporary, destination)
    except OSError:
        import shutil
        shutil.copyfile(temporary, destination)
        with open(destination, "r+b") as stream:
            os.fsync(stream.fileno())
        temporary.unlink(missing_ok=True)

_active_locks = {}

@contextmanager
def project_lock(directory):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    dir_key = str(directory)
    with _guard:
        lock = _locks.setdefault(dir_key, threading.RLock())
    with lock:
        current_tid = threading.get_ident()
        with _guard:
            active = _active_locks.get(dir_key)
            if active and active["thread_id"] == current_tid:
                active["depth"] += 1
                is_reentrant = True
            else:
                is_reentrant = False
        if is_reentrant:
            try:
                yield
            finally:
                with _guard:
                    _active_locks[dir_key]["depth"] -= 1
            return

        stream = open(directory / ".workflow.lock", "a+b")
        try:
            stream.seek(0)
            if not stream.read(1):
                stream.write(b"0")
                stream.flush()
            deadline = time.monotonic() + 60
            while True:
                try:
                    stream.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except (OSError, BlockingIOError):
                    if time.monotonic() >= deadline:
                        raise TimeoutError("项目正在执行其他操作，请稍后重试")
                    time.sleep(.05)
            with _guard:
                _active_locks[dir_key] = {"thread_id": current_tid, "depth": 1, "stream": stream}
            try:
                yield
            finally:
                with _guard:
                    _active_locks.pop(dir_key, None)
                stream.seek(0)
                try:
                    if os.name == "nt":
                        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
        finally:
            stream.close()

def next_version(directory, requested="v1"):
    numbers = [int(requested[1:]) - 1]
    for path in Path(directory).glob("v*"):
        match = re.match(r"^v(\d+)(?:[_.]|$)", path.name)
        if match:
            numbers.append(int(match.group(1)))
    return "v" + str(max(numbers) + 1)
