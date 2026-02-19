"""Stub multiprocessing for WASI - single process only, synchronous execution."""

import threading
from . import queues


class _StubLock:
    def __init__(self):
        self._lock = threading.Lock()

    def acquire(self, block=True, timeout=None):
        return self._lock.acquire(blocking=block, timeout=timeout if timeout else -1)

    def release(self):
        self._lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()


class _CurrentProcess:
    name = "MainProcess"
    pid = 1
    daemon = False


class _ParentProcess:
    """Fake parent process for worker context."""
    name = "MainProcess"
    pid = 0
    daemon = False


# Global flag to track if we're in worker context
_in_worker_context = False
_parent_process = None


def enter_worker_context():
    """Call this when entering worker process context."""
    global _in_worker_context, _parent_process
    _in_worker_context = True
    _parent_process = _ParentProcess()


def exit_worker_context():
    """Call this when exiting worker process context."""
    global _in_worker_context, _parent_process
    _in_worker_context = False
    _parent_process = None


def parent_process():
    """Return parent process - None if main, fake parent if in worker."""
    return _parent_process


class Process:
    """Stub Process that runs synchronously in the main thread."""
    _counter = 0

    def __init__(self, group=None, target=None, name=None, args=(), kwargs=None, daemon=None):
        Process._counter += 1
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}
        self._name = name or f"Process-{Process._counter}"
        self._daemon = daemon
        self._started = False
        self._exitcode = None
        self._pid = Process._counter

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, value):
        self._name = value

    @property
    def daemon(self):
        return self._daemon

    @daemon.setter
    def daemon(self, value):
        self._daemon = value

    @property
    def pid(self):
        return self._pid

    @property
    def exitcode(self):
        return self._exitcode

    def start(self):
        self._started = True
        # Run synchronously - no actual process spawning in WASI
        # Enter worker context so that parent_process() returns non-None
        enter_worker_context()
        try:
            self.run()
        finally:
            exit_worker_context()

    def run(self):
        if self._target:
            try:
                self._target(*self._args, **self._kwargs)
                self._exitcode = 0
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._exitcode = 1

    def join(self, timeout=None):
        # Already completed synchronously
        pass

    def is_alive(self):
        return False  # Always completed since we run synchronously

    def terminate(self):
        pass

    def kill(self):
        pass


class _StubContext:
    Process = Process
    Queue = queues.Queue
    SimpleQueue = queues.SimpleQueue
    JoinableQueue = queues.JoinableQueue

    @staticmethod
    def Lock():
        return _StubLock()

    @staticmethod
    def RLock():
        return threading.RLock()

    @staticmethod
    def parent_process():
        return _parent_process  # Returns None in main, fake parent in worker

    @staticmethod
    def current_process():
        return _CurrentProcess()


def get_context(method=None):
    return _StubContext()


Lock = _StubContext.Lock
RLock = _StubContext.RLock
current_process = _StubContext.current_process
Queue = queues.Queue
SimpleQueue = queues.SimpleQueue
JoinableQueue = queues.JoinableQueue
