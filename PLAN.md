# rust-ansible Implementation Plan

## Project Goal

Build a single Rust binary that embeds WASIX Python + ansible-core, using Wasmer runtime to execute playbooks locally.

## Current Status: PING MODULE WORKING

Full playbook execution works end-to-end. The ping module returns `{"ping": "pong"}` successfully.

### What Works

| Component | Status | Notes |
|-----------|--------|-------|
| Wasmer runtime | ✅ | v7.0.1 via mise |
| WASIX Python | ✅ | 3.13.0rc2 from `python/python` package |
| Threading | ✅ | `threading.Thread` works in WASIX |
| ansible import | ✅ | v2.20.2 |
| PlaybookCLI | ✅ | Imports with stubs |
| `--version` | ✅ | Full output works |
| Playbook parsing | ✅ | YAML loads, inventory parsed |
| Task queueing | ✅ | PLAY and TASK shown |
| wasi_local plugin | ✅ | Connection plugin works |
| In-process exec | ✅ | Module execution via `exec()` works |
| WorkerProcess | ✅ | Patched _detach, _hard_exit, _run |
| multiprocessing | ✅ | Patches real module, not just stub |
| fcntl | ✅ | lockf AND flock patched |
| Collection loader | ✅ | ansible.builtin metadata loads |
| Task execution | ✅ | No hang, completes with result |
| Pipelining | ✅ | Module via in_data works |
| **Ping module** | ✅ | Returns `{"ping": "pong"}` |

### What Remains

| Component | Status | Notes |
|-----------|--------|-------|
| Rust embedding | ⏳ | Wasmer SDK integration |
| Build system | ⏳ | Asset packaging |
| Binary distribution | ⏳ | Single static binary |
| More module testing | ⏳ | debug, command, etc. |

## Architecture

```
rust-ansible (single binary ~80MB)
├── wasmer runtime (embedded via wasmer crate)
├── WASIX Python WASM (~30MB, from wasmer registry)
├── Python stdlib (bundled with WASIX Python)
├── ansible-core + deps (~15MB, as Python packages)
└── Compatibility stubs (~20KB)
    ├── wasi_bootstrap.py      # OS/socket/subprocess patches
    ├── wasi_local.py          # In-process module executor
    ├── ctypes/                # wcwidth/wcswidth stubs
    ├── fcntl.py               # File control stubs
    ├── grp.py                 # Group database stub
    ├── pwd.py                 # Password database stub
    ├── termios.py             # Terminal control stubs
    ├── multiprocessing/       # Process/Queue stubs
    └── ansible.cfg            # WASI-specific config
```

## Key Discovery

WASIX provides **threading but NOT subprocess**. Ansible's local connection plugin uses `subprocess.Popen` to execute modules. We solved this with a custom `wasi_local` connection plugin that uses `exec()` to run modules in-process.

## Implementation Progress

### Phase 1: In-Process Module Executor ✅ COMPLETE

Created `assets/stubs/ansible_plugins/connection/wasi_local.py`:

```python
class Connection(ConnectionBase):
    transport = 'wasi_local'

    def exec_command(self, cmd, in_data=None, sudoable=True):
        # Parse Python script from command
        # Execute via exec() in isolated namespace
        # Capture stdout/stderr and exit code
        # Return (rc, stdout, stderr) tuple
```

**Key insight:** Ansible modules are Python scripts that:
1. Read JSON args from environment or stdin
2. Do work
3. Print JSON result to stdout
4. Call `sys.exit(0)` or `sys.exit(1)`

We intercept this by:
1. Reading the module script file
2. Executing with `exec()` in a new namespace
3. Capturing stdout via `io.StringIO`
4. Catching `SystemExit` for return code

### Phase 2: Bootstrap System ✅ COMPLETE

Created `assets/stubs/wasi_bootstrap.py`:

```python
def initialize():
    patch_os_module()      # getuid, register_at_fork, etc.
    patch_socket_module()  # getaddrinfo stub
    patch_subprocess_module()  # Clear error messages
    configure_ansible()    # Set plugin paths, config
```

Patches applied:
- `os.register_at_fork` - no-op (no fork in WASI)
- `os.getuid/getgid` - return fake values
- `os.waitpid` - stub that returns immediately
- `os.fork` - raises clear error
- `os.setsid/killpg/kill` - no-op stubs
- `socket.getaddrinfo` - localhost-only resolution
- `subprocess.Popen` - raises clear error with guidance
- `fcntl.lockf` - no-op stub on builtin module
- `WorkerProcess._detach` - skip stdio redirect, use StringIO
- `WorkerProcess._hard_exit` - raise exception instead of os._exit()
- `WorkerProcess._run` - restore stdout/stderr after execution
- `multiprocessing.get_context` - returns WASI-compatible context
- `multiprocessing.Process` - synchronous execution in main thread

### Phase 3: Rust Embedding ⏳ PENDING

**Cargo.toml:**
```toml
[package]
name = "rust-ansible"
version = "0.1.0"
edition = "2021"

[dependencies]
wasmer = "7.0"
wasmer-wasix = "0.39"
clap = { version = "4", features = ["derive"] }
tempfile = "3"
anyhow = "1"

[build-dependencies]
reqwest = { version = "0.12", features = ["blocking"] }
```

**src/main.rs implementation needed:**
```rust
use wasmer::{Module, Store};
use wasmer_wasix::WasiEnv;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    // 1. Extract embedded assets to temp dir
    // 2. Create Wasmer store and load WASIX Python
    // 3. Configure WASIX environment with mounts
    // 4. Run ansible-playbook with args
}
```

### Phase 4: Build System ⏳ PENDING

Need to create `build.rs` that:
1. Downloads WASIX Python WASM from wasmer registry
2. Packages ansible-core + dependencies
3. Bundles stubs
4. Embeds everything in binary

## Directory Structure

```
rust-ansible/
├── .mise.toml              # ✅ Tools: wasmer, rust, uv
├── Cargo.toml              # ✅ Dependencies defined
├── PLAN.md                 # This file
├── src/
│   └── main.rs             # ✅ Skeleton with TODOs
├── assets/
│   └── stubs/              # ✅ WASI compatibility layer
│       ├── wasi_bootstrap.py
│       ├── sitecustomize.py
│       ├── ansible.cfg
│       ├── ansible_plugins/
│       │   └── connection/
│       │       └── wasi_local.py
│       ├── ctypes/
│       ├── fcntl.py
│       ├── grp.py
│       ├── pwd.py
│       ├── termios.py
│       ├── multiprocessing/
│       ├── threading_patch.py
│       └── wasi_strategy_patch.py
└── test_wasi_connection.py # ✅ Test script (passing)
```

## Testing Commands

```bash
# Setup environment
cd /home/denys/go-ansible/rust-ansible
mise trust && mise install
eval "$(mise activate bash)"

# Test WASIX Python threading
wasmer run python/python -- -c "import threading; t=threading.Thread(target=lambda: print('works')); t.start(); t.join()"

# Test wasi_local connection plugin
wasmer run python/python \
  --volume ./assets/stubs:/stubs \
  --volume ../feasibility/pysite/.venv/lib/python3.14/site-packages:/site-packages \
  --volume .:/workspace \
  --env HOME=/workspace \
  --env USER=wasi \
  --env PYTHONPATH=/stubs:/site-packages \
  --cwd /workspace \
  -- /workspace/test_wasi_connection.py

# Test ansible-playbook --version
wasmer run python/python \
  --volume ./assets/stubs:/stubs \
  --volume ../feasibility/pysite/.venv/lib/python3.14/site-packages:/site-packages \
  --volume ../feasibility/workspace:/workspace \
  --env HOME=/workspace \
  --env USER=wasi \
  --env PYTHONPATH=/stubs:/site-packages \
  --cwd /workspace \
  -- -m ansible.cli.playbook --version
```

## Critical Next Steps

1. **Test full playbook execution** - Run ping module with wasi_local connection
   ```bash
   # Create test playbook that uses connection: wasi_local
   # Run with wasmer and verify JSON output
   ```

2. **Rust Wasmer embedding** - Implement src/main.rs
   - Extract assets to temp dir
   - Configure WasiEnv with proper mounts
   - Pass CLI args to ansible-playbook

3. **Build system** - Create build.rs
   - Download WASIX Python WASM
   - Package site-packages
   - Embed with include_dir or similar

4. **Single binary** - Final packaging
   - Static linking
   - Strip symbols
   - Test on clean system

## Module Execution Deep Dive

Ansible module execution flow (normal):
```
ActionBase._execute_module()
  → modify_module() [wraps module in AnsiballZ zipfile]
  → _low_level_execute_command()
  → Connection.exec_command()  # ← subprocess.Popen here
  → subprocess.Popen(python wrapper_script.py)
```

WASIX flow (implemented):
```
ActionBase._execute_module()
  → modify_module() [same AnsiballZ wrapper]
  → _low_level_execute_command()
  → wasi_local.exec_command()  # ← our plugin
  → exec(compile(script, ...), namespace)  # In-process!
  → Capture stdout, catch SystemExit
```

## Test Results (Latest)

### Full Playbook Execution - SUCCESS
```
=== Task Execution Trace ===
PLAY [Test Play] ***************************************************************
TASK [Test ping] ***************************************************************
   Play result: 0

Module stdout: {"ping": "pong", "invocation": {"module_args": {"data": "pong"}}}
```

### Key Fixes Applied

1. **fcntl.flock patch** - WASI Python's fcntl module has neither lockf nor flock implemented. Both needed patching.

2. **Collection loader initialization** - `init_plugin_loader()` must be called for ansible.builtin metadata to load.

3. **Pipelining support** - Ansible passes module scripts via in_data when pipelining is enabled. The wasi_local plugin now handles this with `_exec_pipelined_script()`.

4. **Shell command handling** - Ansible wraps commands in `/bin/sh -c`. The plugin now handles:
   - Python discovery: `command -v python*`
   - Python availability: `python && sleep 0`
   - Basic shell commands: echo, mkdir, chmod, rm

## Success Criteria

1. ~~`rust-ansible -i localhost, -m ping all` returns pong~~ ✅ Works via wasmer
2. `rust-ansible playbook.yml` executes simple playbooks ⏳ Need Rust binary
3. Single static binary, no external dependencies ⏳ Build system
4. Works on Linux x86_64 (primary), macOS/Windows (stretch)

## Estimated Remaining Work

| Task | Status |
|------|--------|
| In-process module executor | ✅ Complete |
| Bootstrap/patches | ✅ Complete |
| Full playbook test | ✅ Complete |
| Rust wasmer embedding | ⏳ Next |
| Build system | ⏳ Medium effort |
| Testing/polish | ⏳ Medium effort |

## References

- Wasmer Rust SDK: https://docs.wasmer.io/sdk/rust
- WASIX docs: https://wasix.org/
- Ansible module development: https://docs.ansible.com/ansible/latest/dev_guide/developing_modules.html
- Mitogen for Ansible: https://mitogen.networkgenomics.com/ansible_detailed.html

## Feasibility Resources

Located at `/home/denys/go-ansible/feasibility/`:
- `pysite/.venv/lib/python3.14/site-packages/` - ansible-core 2.20.2 + deps
- `stubs/` - Original compatibility stubs
- `workspace/` - Test playbooks and inventory
- `feasibility-report.md` - Detailed WASI Python findings
