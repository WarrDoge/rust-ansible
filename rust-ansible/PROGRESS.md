# rust-ansible Progress

## Current Status: Rust Embedding In Progress

Last updated: 2026-02-19

### Phase Summary

| Phase | Status | Notes |
|-------|--------|-------|
| 1. WASI Compatibility Stubs | Complete | All patches working |
| 2. In-Process Module Executor | Complete | wasi_local plugin works |
| 3. Rust Wasmer Embedding | In Progress | Compiles, testing runtime |
| 4. Asset Packaging | Not Started | build.rs for embedding |
| 5. Single Binary Distribution | Not Started | Final packaging |

---

## Phase 3: Rust Embedding Details

### Completed

- [x] Cargo.toml configured with wasmer 7.0, wasmer-wasix 0.700
- [x] Cranelift compiler with exception handling enabled
- [x] Tokio async runtime integration
- [x] UnionFileSystem for mounting host directories
- [x] CLI argument parsing with clap
- [x] Build succeeds with `cargo +nightly build --release`

### In Progress

- [ ] First runtime test - Cranelift compiling Python WASM (~20+ min)
- [ ] Module caching - Save compiled module to avoid recompilation

### Not Started

- [ ] Test simple Python execution
- [ ] Test ansible import
- [ ] Test playbook execution
- [ ] Pre-compile module at build time

---

## Build Requirements

```bash
# Rust nightly required (wasmer 7.0 needs Rust 1.91+)
rustup install nightly

# Build
cargo +nightly build --release

# WASIX Python must be unpacked
wasmer package download python/python -o /tmp/python.webc
wasmer package unpack --format webc -o /tmp/python_unpacked /tmp/python.webc
```

---

## Runtime Dependencies (Development)

These paths are hardcoded defaults for development:

| Path | Contents | Source |
|------|----------|--------|
| `/tmp/python_unpacked/python` | WASIX Python WASM | wasmer registry |
| `/tmp/python_unpacked/root/` | Python stdlib + shared libs | wasmer registry |
| `../feasibility/pysite/.venv/lib/python3.14/site-packages/` | ansible-core 2.20.2 | pip install |
| `./assets/stubs/` | WASI compatibility layer | This repo |

---

## Known Issues

### 1. Slow First-Run Compilation

Cranelift compilation of the 10.5MB Python WASM takes 20+ minutes on first run.

**Solution needed**: Cache compiled module to disk, or pre-compile at build time.

### 2. Pre-compiled Module Incompatibility

Modules compiled with `wasmer` CLI (LLVM backend) are incompatible with Cranelift-based runtime.

**Workaround**: Delete any `.wasmu` files and let Cranelift compile from source.

### 3. Nightly Rust Required

wasmer 7.0 requires Rust 1.91+, but stable is 1.88.

**Workaround**: Use `cargo +nightly build`.

---

## Architecture

```
rust-ansible binary
├── wasmer 7.0 runtime (Cranelift compiler)
├── wasmer-wasix 0.700 (WASI/WASIX implementation)
├── tokio (async runtime for wasmer-wasix)
└── virtual-fs (UnionFileSystem for mounts)

Runtime mounts:
├── /lib         → python_unpacked/root/lib (libsqlite3.so, etc.)
├── /usr         → python_unpacked/root/usr (Python stdlib)
├── /stubs       → assets/stubs (WASI patches)
├── /site-packages → ansible-core + deps
└── /workspace   → current directory (playbooks)
```

---

## Test Commands

```bash
# Simple Python test
./target/release/rust-ansible -- -c "print('hello')"

# Ansible version
./target/release/rust-ansible --version

# Run playbook (once working)
./target/release/rust-ansible playbook.yml -i inventory.ini
```

---

## Next Steps

1. Wait for/complete first runtime test
2. Add module caching to avoid recompilation
3. Test ansible import and playbook execution
4. Create build.rs for asset embedding
5. Package as single static binary

---

## Reference

- [PLAN.md](./PLAN.md) - Full project plan and WASI compatibility details
- [Wasmer 7.0 Docs](https://docs.wasmer.io/)
- [wasmer-wasix crate](https://crates.io/crates/wasmer-wasix)
