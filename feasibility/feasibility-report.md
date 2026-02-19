# go-ansible WASI Feasibility Report

## Summary

**Recommendation: NO-GO for full ansible-core under standard WASI Python**

While ansible-core imports successfully with patches, fundamental architectural incompatibilities prevent playbook execution. The required workarounds are extensive and fragile.

## Test Environment

- **CPython WASI**: 3.14.3 (brettcannon/cpython-wasi-build)
- **WASI Runtime**: wasmtime 41.0.3
- **ansible-core**: 2.20.2
- **Host OS**: Linux x86_64

## Test Results

### Passed

| Test | Status | Notes |
|------|--------|-------|
| Basic Python execution | PASS | `python.wasm -c "print('hello')"` works |
| Standard library imports | PASS | json, os, sys, etc. |
| jinja2 import | PASS | v3.1.6 |
| PyYAML import | PASS | v6.0.3 (pure Python mode, no C loader) |
| ansible package import | PASS | After patching socket |
| PlaybookCLI import | PASS | After extensive patching |
| ansible-playbook --version | PASS | Shows version info correctly |
| Collection loader init | PASS | `init_plugin_loader()` works |
| Inventory parsing | PASS | Hosts detected correctly |
| Playbook parsing | PASS | YAML loads correctly |

### Failed

| Test | Status | Blocker |
|------|--------|---------|
| Playbook execution | FAIL | Multiple architectural issues |
| Module execution | FAIL | Subprocess not available |
| Threading | FAIL | WASI Python has no thread support |

## Critical Blockers

### 1. No Threading Support (CRITICAL)

WASI Python cannot start new threads:
```
RuntimeError: can't start new thread
```

Ansible's strategy plugins require a background thread for result processing (`results_thread_main`). This is fundamental to ansible's architecture.

**Workaround attempted**: Stub threading module and patch strategy base class to process results synchronously. Partially successful but incomplete.

### 2. No Subprocess/Fork (CRITICAL)

WASI has no process spawning capability:
- `os.fork()` not available
- `subprocess` module non-functional
- `os.waitpid()` not available (stubbed)

Ansible executes modules by spawning Python subprocesses. Without this, module execution fails.

**Impact**: Cannot execute any ansible modules (ping, debug, copy, file, etc.)

### 3. Limited Network Stack

WASI Python's socket module lacks:
- `socket.getaddrinfo()` - stubbed successfully
- Full TCP/UDP connectivity - not tested for localhost

### 4. Missing OS Primitives

Required extensive stubs for:
- `ctypes` - terminal width detection
- `fcntl` - file descriptor control
- `termios` - terminal handling
- `grp` / `pwd` - user/group database
- `multiprocessing` - process management (heavily stubbed)

## Stubs Created

```
stubs/
├── ctypes/
│   ├── __init__.py    # wcwidth/wcswidth stubs
│   └── util.py        # find_library stub
├── fcntl.py           # ioctl, flock stubs
├── grp.py             # group database stub
├── multiprocessing/
│   ├── __init__.py    # Process, Lock, Context stubs
│   └── queues.py      # Queue, SimpleQueue stubs
├── pwd.py             # password database stub
├── termios.py         # terminal control stubs
├── threading_patch.py # No-op threading
└── wasi_strategy_patch.py  # Synchronous result processing
```

## Execution Flow Analysis

1. **Import phase**: Success with patches
2. **CLI parsing**: Success
3. **Plugin loading**: Success
4. **Inventory parsing**: Success
5. **Playbook loading**: Success
6. **Task execution**: FAILS - worker process mechanism broken

The worker process architecture (`ansible.executor.process.worker.WorkerProcess`) assumes multiprocessing:
- Extends `multiprocessing.Process`
- Communicates via `multiprocessing.Queue`
- Requires separate process context for module execution

## Alternative Approaches

### Option A: WASIX Python (Recommended for further exploration)

WASIX (WebAssembly System Interface eXtended) adds:
- Thread support
- Expanded POSIX compatibility

Would require:
- Different Python build (wasmer-based)
- Different runtime (wasmer instead of wasmtime/wazero)

### Option B: Patch Ansible for Single-Process Mode

Create a custom ansible fork with:
- Synchronous module execution via importlib
- No worker processes
- Direct function calls instead of subprocess

Estimated effort: High (significant ansible internals modification)

### Option C: Limited Module Subset

Implement only specific modules natively in Go:
- ping (trivial)
- debug (trivial)
- copy (file operations)
- file (file operations)
- template (jinja2 rendering)

Would not be "ansible" but could run simple playbooks.

### Option D: Container-Based Execution

Go binary orchestrates Docker/Podman with real ansible:
- Full ansible compatibility
- Requires container runtime on host
- Not truly embedded

## Conclusion

Standard WASI Python lacks the process and threading primitives required by ansible-core's architecture. The executor assumes multiprocessing for parallelism and subprocess for module execution.

**Next Steps** (if pursuing further):
1. Investigate WASIX Python builds with thread support
2. Evaluate effort for ansible single-process fork
3. Consider limited Go-native module implementation

## Files

Test artifacts in `/home/denys/go-ansible/feasibility/`:
- `cpython-wasi.zip` - CPython WASI build
- `python.wasm` - Python interpreter
- `lib/` - Python standard library
- `pysite/` - ansible-core installation
- `stubs/` - WASI compatibility stubs
- `workspace/` - test playbooks and scripts
