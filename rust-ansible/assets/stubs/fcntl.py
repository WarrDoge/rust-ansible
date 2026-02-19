"""Stub fcntl for WASI."""

LOCK_EX = 2
LOCK_NB = 4
LOCK_SH = 1
LOCK_UN = 8
F_GETFL = 3
F_SETFL = 4
F_GETFD = 1
F_SETFD = 2

def fcntl(fd, op, arg=0):
    return 0

def ioctl(fd, request, arg=None, mutate_flag=True):
    # Return zeros for terminal size query
    if arg is not None:
        return arg
    return b'\x00' * 8

def flock(fd, operation):
    pass

def lockf(fd, operation, length=0, start=0, whence=0):
    pass
