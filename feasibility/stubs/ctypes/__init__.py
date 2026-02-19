"""Minimal ctypes stub for WASI."""

class c_int:
    pass

class c_wchar:
    pass

class c_wchar_p:
    pass

def sizeof(t):
    return 4

def _wcwidth(c):
    """Approximate wcwidth: single-width for ASCII, double for CJK."""
    if ord(c) < 128:
        return 1
    return 2

def _wcswidth(s, n):
    """Approximate wcswidth."""
    return sum(1 if ord(c) < 128 else 2 for c in s[:n])

class _StubFunction:
    def __init__(self, func):
        self._func = func
        self.argtypes = None
        self.restype = None

    def __call__(self, *args, **kwargs):
        return self._func(*args, **kwargs)

class _StubLibc:
    def __init__(self):
        self.wcwidth = _StubFunction(_wcwidth)
        self.wcswidth = _StubFunction(_wcswidth)

class cdll:
    @staticmethod
    def LoadLibrary(name):
        return _StubLibc()

class ArgumentError(Exception):
    pass
