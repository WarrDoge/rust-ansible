"""Bootstrap script for WASI ansible."""
import sys
sys.path.insert(0, '/stubs')
sys.path.insert(1, '/site-packages')

# Patch threading FIRST before anything imports it
from threading_patch import patch_threading
patch_threading()

# Patch socket
import socket
import _socket
def stub_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    port = int(port)
    if host in ('localhost', '127.0.0.1', '::1', None, ''):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', port))]
    raise socket.gaierror(8, 'nodename nor servname provided, or not known')
_socket.getaddrinfo = stub_getaddrinfo
socket.getaddrinfo = stub_getaddrinfo

# Patch os for WASI compatibility
import os

os.getuid = lambda: 1000
os.getgid = lambda: 1000
os.geteuid = lambda: 1000
os.getegid = lambda: 1000
os.register_at_fork = lambda **kwargs: None

# Stub waitpid for connection plugins
def stub_waitpid(pid, options):
    return (pid, 0)
os.waitpid = stub_waitpid

# Stub fork
def stub_fork():
    raise OSError("fork() not supported in WASI")
os.fork = stub_fork

# Stub pipe for subprocess-like operations
_pipe_counter = [100]
def stub_pipe():
    _pipe_counter[0] += 2
    return (_pipe_counter[0], _pipe_counter[0] + 1)
if not hasattr(os, 'pipe'):
    os.pipe = stub_pipe

# Stub setpgid/getpgid
os.setpgid = lambda pid, pgid: None
os.getpgid = lambda pid: pid
os.setsid = lambda: 1000
os.killpg = lambda pgid, sig: None

# Stub os.kill
def stub_kill(pid, sig):
    pass
os.kill = stub_kill

def apply_strategy_patch():
    """Apply strategy patch after ansible is imported."""
    from wasi_strategy_patch import patch_strategy_base
    patch_strategy_base()
