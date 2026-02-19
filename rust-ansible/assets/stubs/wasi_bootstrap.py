"""
WASI/WASIX bootstrap for ansible.

This module must be imported before ansible to patch missing functionality
and configure ansible to use the in-process connection plugin.

Usage in rust-ansible:
    Set PYTHONPATH=/stubs:/site-packages
    Set WASI_BOOTSTRAP=1
    Python will auto-import via sitecustomize or explicit import

Or import directly:
    import wasi_bootstrap
    wasi_bootstrap.initialize()
"""

import os
import sys

_initialized = False


def patch_os_module():
    """Patch os module with missing WASI functions."""

    # register_at_fork - no-op since fork doesn't exist in WASI
    if not hasattr(os, 'register_at_fork'):
        def stub_register_at_fork(*, before=None, after_in_parent=None, after_in_child=None):
            pass  # No-op - fork doesn't exist in WASI/WASIX
        os.register_at_fork = stub_register_at_fork

    # getuid/getgid - return fake values
    if not hasattr(os, 'getuid'):
        os.getuid = lambda: 1000
    if not hasattr(os, 'getgid'):
        os.getgid = lambda: 1000
    if not hasattr(os, 'geteuid'):
        os.geteuid = lambda: 1000
    if not hasattr(os, 'getegid'):
        os.getegid = lambda: 1000

    # waitpid - stub that returns immediately
    if not hasattr(os, 'waitpid'):
        def stub_waitpid(pid, options):
            return (pid, 0)
        os.waitpid = stub_waitpid

    # fork - not available, raise clear error
    if not hasattr(os, 'fork'):
        def stub_fork():
            raise OSError("fork() not available in WASI/WASIX")
        os.fork = stub_fork

    # getlogin - return USER env var
    if not hasattr(os, 'getlogin'):
        os.getlogin = lambda: os.environ.get('USER', 'wasi')

    # setuid/setgid - no-op (no privilege escalation in WASI)
    if not hasattr(os, 'setuid'):
        os.setuid = lambda uid: None
    if not hasattr(os, 'setgid'):
        os.setgid = lambda gid: None
    if not hasattr(os, 'seteuid'):
        os.seteuid = lambda uid: None
    if not hasattr(os, 'setegid'):
        os.setegid = lambda gid: None

    # WNOHANG constant for waitpid
    if not hasattr(os, 'WNOHANG'):
        os.WNOHANG = 1

    # setsid - no-op (no process groups in WASI)
    if not hasattr(os, 'setsid'):
        os.setsid = lambda: None

    # killpg - no-op (no process groups in WASI)
    if not hasattr(os, 'killpg'):
        os.killpg = lambda pgid, sig: None

    # kill - no-op (no signals to other processes in WASI)
    if not hasattr(os, 'kill'):
        os.kill = lambda pid, sig: None

    # getpgid - return fake value
    if not hasattr(os, 'getpgid'):
        os.getpgid = lambda pid: pid

    # setpgid - no-op
    if not hasattr(os, 'setpgid'):
        os.setpgid = lambda pid, pgid: None


def patch_fcntl_module():
    """Patch fcntl module with missing WASI functions.

    The built-in fcntl module takes precedence over our stub,
    so we need to patch it directly. Both lockf and flock need
    to be stubbed for WASI compatibility.
    """
    try:
        import fcntl

        # lockf is not implemented in WASI Python - make it a no-op
        def stub_lockf(fd, operation, length=0, start=0, whence=0):
            pass

        # flock is also not implemented in WASI Python - make it a no-op
        # The error message from WASI says "lockf() is not implemented"
        # even when flock is called, which is confusing but expected.
        def stub_flock(fd, operation):
            pass

        # Patch lockf
        if hasattr(fcntl, 'lockf'):
            fcntl.lockf = stub_lockf
        else:
            setattr(fcntl, 'lockf', stub_lockf)

        # Patch flock
        if hasattr(fcntl, 'flock'):
            fcntl.flock = stub_flock
        else:
            setattr(fcntl, 'flock', stub_flock)

    except ImportError:
        pass  # fcntl not available at all


def patch_socket_module():
    """Patch socket module with missing WASI functions."""
    import socket

    if not hasattr(socket, '_original_getaddrinfo'):
        socket._original_getaddrinfo = getattr(socket, 'getaddrinfo', None)

        def stub_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
            """Stub getaddrinfo that only resolves localhost."""
            # Handle localhost variants
            if host in (None, '', 'localhost', '127.0.0.1', '::1'):
                # Return IPv4 localhost
                return [
                    (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', port or 0)),
                ]
            # For other hosts, return empty (connection will fail gracefully)
            return []

        socket.getaddrinfo = stub_getaddrinfo


def patch_subprocess_module():
    """Patch subprocess to give clear error messages in WASI."""
    import subprocess

    _original_popen_init = subprocess.Popen.__init__

    def patched_popen_init(self, args, **kwargs):
        """Raise clear error that subprocess is not available."""
        # Check if this looks like a Python script execution
        args_str = str(args)
        if '.py' in args_str or 'python' in args_str.lower():
            raise OSError(
                f"subprocess.Popen not available in WASI/WASIX. "
                f"Use the wasi_local connection plugin for module execution. "
                f"Command was: {args[:100] if isinstance(args, str) else args[:3]}..."
            )
        raise OSError(
            f"subprocess.Popen not available in WASI/WASIX. "
            f"Command was: {args[:100] if isinstance(args, str) else args[:3]}..."
        )

    subprocess.Popen.__init__ = patched_popen_init


def configure_ansible():
    """Configure ansible to use WASI-compatible settings."""
    stubs_dir = os.path.dirname(os.path.abspath(__file__))

    # Point to our ansible.cfg
    ansible_cfg = os.path.join(stubs_dir, 'ansible.cfg')
    if os.path.exists(ansible_cfg):
        os.environ.setdefault('ANSIBLE_CONFIG', ansible_cfg)

    # Add our plugin directory to ansible's plugin path
    plugins_dir = os.path.join(stubs_dir, 'ansible_plugins', 'connection')
    if os.path.isdir(plugins_dir):
        existing = os.environ.get('ANSIBLE_CONNECTION_PLUGINS', '')
        if existing:
            os.environ['ANSIBLE_CONNECTION_PLUGINS'] = f"{plugins_dir}:{existing}"
        else:
            os.environ['ANSIBLE_CONNECTION_PLUGINS'] = plugins_dir

    # Force wasi_local connection for localhost
    os.environ.setdefault('ANSIBLE_CONNECTION', 'wasi_local')

    # Disable features that don't work in WASI
    os.environ.setdefault('ANSIBLE_NOCOWS', '1')
    os.environ.setdefault('ANSIBLE_NOCOLOR', '0')
    os.environ.setdefault('ANSIBLE_RETRY_FILES_ENABLED', 'False')

    # Disable fact gathering by default (many facts require subprocess)
    os.environ.setdefault('ANSIBLE_GATHERING', 'explicit')


def patch_worker_process():
    """Patch WorkerProcess for WASI mode.

    Patches:
    1. _detach() - skip fd operations but still set up StringIO for stdout/stderr
    2. _hard_exit() - don't call os._exit() (would kill entire runtime)
    """
    try:
        from ansible.executor.process.worker import WorkerProcess
        import io
        import sys

        # Original stdout/stderr (will be restored after worker completes)
        _original_stdout = None
        _original_stderr = None

        def wasi_detach(self):
            """WASI version of _detach - skip fd operations but set up StringIO.

            The original _detach does:
            1. os.setsid() - not needed in WASI
            2. Redirect fds to /dev/null - not needed in WASI
            3. Replace sys.stdout/stderr with StringIO - NEEDED for getvalue()
            4. Close stdin - skip to avoid issues

            We only do step 3 since _run() checks stdout.getvalue().
            """
            nonlocal _original_stdout, _original_stderr

            # Save original stdout/stderr to restore later
            _original_stdout = sys.stdout
            _original_stderr = sys.stderr

            # Replace with StringIO - this is what _run() expects
            sys.stdout = io.StringIO()
            sys.stderr = io.StringIO()

        WorkerProcess._detach = wasi_detach

        # Also patch the _run end to restore stdout/stderr
        _original_run = WorkerProcess._run

        def wasi_run(self):
            """WASI version of _run that restores stdout/stderr."""
            nonlocal _original_stdout, _original_stderr
            try:
                return _original_run(self)
            finally:
                # Restore original stdout/stderr
                if _original_stdout is not None:
                    sys.stdout = _original_stdout
                    _original_stdout = None
                if _original_stderr is not None:
                    sys.stderr = _original_stderr
                    _original_stderr = None

        WorkerProcess._run = wasi_run

        # Replace _hard_exit to raise exception instead of os._exit()
        # In normal ansible, workers are forked processes, so _exit just kills
        # the worker. In WASI, we run synchronously so _exit would kill everything.
        def wasi_hard_exit(self, e):
            """In WASI, raise an exception instead of calling os._exit()."""
            nonlocal _original_stdout, _original_stderr
            # Restore stdout/stderr before raising
            if _original_stdout is not None:
                sys.stdout = _original_stdout
                _original_stdout = None
            if _original_stderr is not None:
                sys.stderr = _original_stderr
                _original_stderr = None

            from ansible.errors import AnsibleError
            raise AnsibleError(f"Worker hard exit: {e}")

        WorkerProcess._hard_exit = wasi_hard_exit

    except ImportError:
        pass


def init_collection_loader():
    """Initialize the ansible collection loader.

    This is required for ansible.builtin and other collections to work
    properly. The collection finder needs to be installed in sys.meta_path
    before modules can be executed.
    """
    try:
        from ansible.plugins.loader import init_plugin_loader
        init_plugin_loader()
    except Exception as e:
        # Log but don't fail - some functionality may still work
        import sys
        print(f"Warning: Failed to initialize collection loader: {e}",
              file=sys.stderr)


def apply_ansible_patches():
    """Apply patches to ansible internals after import."""
    # Patch WorkerProcess first
    patch_worker_process()

    # Initialize the collection loader for ansible.builtin support
    init_collection_loader()

    try:
        # Patch strategy base for synchronous result processing
        # Only needed if threading is not available (standard WASI)
        # WASIX has real threading, so this may not be needed
        import threading
        try:
            # Test if threading actually works
            t = threading.Thread(target=lambda: None)
            t.start()
            t.join()
            # Threading works (WASIX), no need to patch strategy
        except RuntimeError:
            # Threading broken (standard WASI), apply patches
            from wasi_strategy_patch import patch_strategy_base
            patch_strategy_base()
    except ImportError:
        pass


def initialize():
    """Initialize WASI/WASIX environment for ansible."""
    global _initialized
    if _initialized:
        return

    patch_os_module()
    patch_fcntl_module()
    patch_socket_module()
    patch_subprocess_module()
    configure_ansible()

    _initialized = True


# Auto-initialize if this module is imported
if os.environ.get('WASI_BOOTSTRAP', '1') == '1':
    initialize()
