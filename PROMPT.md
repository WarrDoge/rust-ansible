## Agent prompt: go-ansible WASI bundle executed via wazero host binary

You are an expert in Go, WASI, wazero, and Python-on-WASI packaging.

### Objective

Create a distribution that allows users to run:

* `go install ...` or run a single native **Go binary** that behaves like `ansible-playbook` for **localhost-only** automation.

The Go binary must:

* Embed a **WASI build of CPython** (`python.wasm` or equivalent) and a packaged Python filesystem containing **Ansible** and all required Python deps.
* Use **wazero** to execute CPython.wasm under WASI.
* Invoke **Ansible’s real `ansible-playbook` entrypoint** inside the WASI Python runtime (no reimplementation of Ansible logic in Go).

This should follow the same concept as `wasilibs/go-yamllint`, which packages a WASI Python and executes it with wazero. ([GitHub][1])

### Hard constraints

1. **No “rewrite Ansible in Go.”** You must run upstream Ansible (Python).
2. Must support **localhost only** (no SSH, no remote transports).
3. Output should match `ansible-playbook` reasonably (stdout/stderr + exit codes).
4. Deliverable is a **single Go executable** for Linux that embeds everything needed (CPython.wasm + stdlib + site-packages + Ansible). External files are only the user’s playbooks/inventory mounted into WASI.

### Runtime model

* Host: Go + wazero runtime.
* Guest: CPython compiled for WASI.
* Execution: `python.wasm` runs `-m ansible.cli.playbook` (or the `ansible-playbook` console script equivalent) with passed-through args.

### Packaging tasks

Implement build tooling that produces:

* `python.wasm` (or downloads a vetted prebuilt CPython WASI artifact if available and justified).
* A bundled Python filesystem tree containing:

  * Python stdlib for the chosen Python version
  * `ansible` installed into site-packages
  * any required dependencies of Ansible for basic localhost ops
* A Go host binary embedding:

  * `python.wasm` bytes
  * the filesystem tree (compressed) that is expanded into a WASI virtual FS at runtime (or mounted via wazero fs abstraction)

### WASI environment contract

The host must set:

* `PYTHONHOME` and `PYTHONPATH` so Python finds stdlib and site-packages.
* Preopened directories:

  * `/work` mapped to the user’s current directory (read/write) so playbooks can be read.
  * `/tmp` mapped to a temp dir.
* Stdout/stderr passthrough.
* Provide argv passthrough: `ansible-playbook-host -- <ansible-playbook args>`.

### Localhost-only enforcement

Ensure that playbook execution cannot use SSH/remote even if requested:

* Default inventory to localhost if none provided.
* If inventory resolves to non-local addresses, fail fast with a clear error.
* Optionally force `--connection=local` / equivalent settings.
* Ensure any Ansible config defaults are set for local execution (via env or generated `ansible.cfg` in sandbox).

### Deliverables

1. **Repo layout** similar spirit to go-yamllint:

   * `cmd/ansible-playbook-host/`
   * `internal/wasi/` (wazero setup, mounts, env)
   * `internal/pythonbundle/` (embed/extract bundle, versioning)
   * `build/` scripts (build python.wasm and assemble filesystem)
2. **CI**:

   * builds host binary on Linux
   * runs a smoke test that executes a trivial playbook against localhost
3. **Examples**:

   * `examples/ping.yml` or `examples/basic.yml` that uses basic modules on localhost
4. **Documentation**:

   * how to run
   * supported scope (localhost only)
   * how mounts work
   * known limitations (anything that fails in WASI due to missing syscalls, process model, etc.)

### Acceptance test

On Linux:

* `./ansible-playbook-host -- -i localhost, examples/basic.yml`
  must execute successfully with exit code 0 and expected task output.

### Up-front feasibility check (must do first)

Before implementation, produce a short report answering:

* Which CPython WASI build you will use (version, source).
* Whether Ansible and its deps run under WASI CPython without unsupported syscalls.
* Any required patches/workarounds (e.g., subprocess, fork/exec expectations, missing OS features in WASI).
* A minimal proof-of-life command: running `python.wasm -c "import ansible; print(ansible.__version__)"` under wazero.

If the feasibility check fails, propose the smallest set of changes/patches needed to make upstream Ansible work for localhost-only use.

---

## 5 quick details that will prevent wasted cycles

Answer these and I’ll tighten the prompt further (and bake them in as “non-negotiables”):

1. **Ansible major line**: do you need `ansible-core` only, or the full `ansible` package (community bundle)?
2. **Python version preference** (3.11 vs 3.12, etc.), or “whatever works best on WASI”?
3. **Do you need `become`** (sudo) for localhost tasks? (WASI may limit privilege escalation)
4. **Playbook input model**: mount current dir as `/work` and run from there OK?
5. **Bundling strategy**: OK to download prebuilt CPython WASI artifacts in CI, or must build from source every time?

If you reply with just those 5, I’ll produce a final prompt that’s fully pinned down (including exact env vars, wazero FS wiring, and the smoke-test playbook).

[1]: https://github.com/wasilibs/go-yamllint?utm_source=chatgpt.com "A distribution of yamllint that can be used with go run"
