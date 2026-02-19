"""Stub multiprocessing.queues for WASI - single-threaded queue implementations."""

import queue
import threading

class Queue:
    def __init__(self, maxsize=0, ctx=None):
        self._queue = queue.Queue(maxsize)

    def put(self, obj, block=True, timeout=None):
        self._queue.put(obj, block, timeout)

    def get(self, block=True, timeout=None):
        return self._queue.get(block, timeout)

    def qsize(self):
        return self._queue.qsize()

    def empty(self):
        return self._queue.empty()

    def full(self):
        return self._queue.full()

    def put_nowait(self, obj):
        self._queue.put_nowait(obj)

    def get_nowait(self):
        return self._queue.get_nowait()

    def close(self):
        pass

    def join_thread(self):
        pass

class SimpleQueue:
    def __init__(self, ctx=None):
        self._queue = queue.Queue()  # Use regular Queue for get_nowait support

    def put(self, obj):
        self._queue.put(obj)

    def get(self, block=True, timeout=None):
        return self._queue.get(block=block, timeout=timeout)

    def get_nowait(self):
        return self._queue.get_nowait()

    def empty(self):
        return self._queue.empty()

    def close(self):
        pass

class JoinableQueue(Queue):
    def __init__(self, maxsize=0, ctx=None):
        super().__init__(maxsize, ctx)

    def task_done(self):
        self._queue.task_done()

    def join(self):
        self._queue.join()
