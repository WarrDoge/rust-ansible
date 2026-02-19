"""Stub multiprocessing.shared_memory for WASI."""


class SharedMemory:
    """Stub SharedMemory - not supported in WASI."""

    def __init__(self, name=None, create=False, size=0):
        raise OSError("Shared memory not supported in WASI")


class ShareableList:
    """Stub ShareableList - not supported in WASI."""

    def __init__(self, sequence=None, *, name=None):
        raise OSError("Shared memory not supported in WASI")
