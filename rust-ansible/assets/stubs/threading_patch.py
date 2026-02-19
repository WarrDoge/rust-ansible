"""Patch threading.Thread for WASI synchronous execution."""
import threading as _threading_module

# Save original before patching
_original_Thread = _threading_module.Thread
_original_Lock = _threading_module.Lock
_original_RLock = _threading_module.RLock
_original_Condition = _threading_module.Condition


class _NoOpLock:
    """Lock that does nothing - single threaded."""
    def acquire(self, blocking=True, timeout=-1):
        return True

    def release(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def locked(self):
        return False


class _NoOpRLock(_NoOpLock):
    """RLock that does nothing - single threaded."""
    pass


class _NoOpCondition:
    """Condition that does nothing - single threaded."""
    def __init__(self, lock=None):
        self._lock = lock or _NoOpLock()

    def acquire(self, *args, **kwargs):
        return self._lock.acquire(*args, **kwargs)

    def release(self):
        self._lock.release()

    def wait(self, timeout=None):
        return True

    def wait_for(self, predicate, timeout=None):
        return predicate()

    def notify(self, n=1):
        pass

    def notify_all(self):
        pass

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()


class _SyncThread:
    """Thread replacement that doesn't actually thread."""

    _counter = 0

    def __init__(self, group=None, target=None, name=None, args=(), kwargs=None, daemon=None):
        _SyncThread._counter += 1
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}
        self._name = name or f"Thread-{_SyncThread._counter}"
        self._daemon = daemon
        self._started = False
        self._ident = _SyncThread._counter

    @property
    def daemon(self):
        return self._daemon

    @daemon.setter
    def daemon(self, value):
        self._daemon = value

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, value):
        self._name = value

    @property
    def ident(self):
        return self._ident

    def start(self):
        """Don't actually start - WASI doesn't support threads."""
        self._started = True
        # Don't run - will be pumped manually if needed

    def run(self):
        if self._target:
            self._target(*self._args, **self._kwargs)

    def join(self, timeout=None):
        pass

    def is_alive(self):
        return False


def patch_threading():
    """Patch threading module for WASI."""
    _threading_module.Thread = _SyncThread
    _threading_module.Lock = _NoOpLock
    _threading_module.RLock = _NoOpRLock
    _threading_module.Condition = _NoOpCondition
