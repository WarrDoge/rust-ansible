# Project Plan: WASM-Native Node Runtime

> **Status**: Planning phase — pivoting from rust-ansible (Ansible-in-WASM) to a new product.
>
> **Last updated**: 2026-02-20

---

## Table of Contents

1. [Vision and Problem Statement](#vision-and-problem-statement)
2. [Why Existing Tools Fail](#why-existing-tools-fail)
3. [Prior Art: Lessons from rust-ansible](#prior-art-lessons-from-rust-ansible)
4. [Product Definition](#product-definition)
5. [Architecture](#architecture)
6. [Technology Choices and Rationale](#technology-choices-and-rationale)
7. [WASM Benefits and Limitations](#wasm-benefits-and-limitations)
8. [Security Model: Config-Driven Capabilities](#security-model-config-driven-capabilities)
9. [Hot Reload Design](#hot-reload-design)
10. [Convergence Loop](#convergence-loop)
11. [MVP Scope](#mvp-scope)
12. [Future Phases](#future-phases)
13. [Open Questions and Risks](#open-questions-and-risks)
14. [Strategic Context](#strategic-context)
15. [Previous Work Reference](#previous-work-reference)

---

## Vision and Problem Statement

### The Vision

Move the industry toward adopting WebAssembly as a polyglot runtime that can execute
anywhere, reducing dependency on Docker containers. Inspired by the "OS as appliance"
model (Flatcar + Ignition, Siderolabs Talos OS), where the OS is immutable and minimal,
and workloads are managed through APIs rather than SSH.

### The Problem

There is no single tool that provides a **universal API layer between app deployment and
OS configuration**. Today, running a realistic production workload requires stitching
together multiple tools:

```
Terraform provisions VM
  -> cloud-init/Ignition configures OS (one-shot, boot-time only)
    -> SSH + Ansible/scripts deploy Docker Compose stack
      -> hope nothing drifts
```

**Docker Compose** handles ~80% of the work (app deployment), but the remaining 20% —
disks, volumes, firewalls, package updates, security — must be managed outside Compose.
There is no unified declaration for "run this app AND configure these OS primitives."

**Concrete example**: "Run Jira on port 8080 and firewall all other ports." No existing
tool handles both halves of that sentence in a single, declarative config:

- **Docker Compose**: runs Jira, cannot manage firewall
- **Ansible**: can manage firewall, but needs Python+SSH, not API-driven, not continuous
- **Nomad**: runs Jira, cannot manage host firewall
- **k3s/Kubernetes**: can do both (via NetworkPolicy + workloads), but requires full
  Kubernetes — massive complexity overhead for a single node
- **Talos OS**: API-driven OS config + workloads, but **requires Kubernetes** for all
  workloads — no Compose-like simplicity

### The Gap

> "Talos-like API-driven node management, with Compose-level simplicity for workloads,
> plus declarative OS primitive management — no Kubernetes, no SSH required."

### What We Want

A single declarative config that can run with almost zero dependencies on any cloud or
bare metal, ideally controllable via Terraform/Pulumi provider during VM provisioning:

```yaml
system:
  firewall:
    default: deny
    ingress:
      - port: 8080
        allow: 0.0.0.0/0
      - port: 22
        allow: 10.0.0.0/8

workloads:
  jira:
    image: atlassian/jira-software:9.12
    ports: ["8080:8080"]
    volumes: ["/data/jira:/var/atlassian/application-data/jira"]
```

One config. One tool. Continuous convergence. API-driven.

---

## Why Existing Tools Fail

### Docker Compose

- Handles apps well with simple YAML
- **Cannot manage OS primitives** (firewall, disks, mounts, sysctl, users)
- No API (just a CLI)
- No continuous convergence / drift detection
- Exposing Docker socket on TCP (even with TLS) is a security anti-pattern

### Ansible

- Can manage both OS and apps
- **Requires Python + SSH** on every target
- Not API-driven — push-based, imperative
- No continuous convergence (runs once, no drift detection)
- Not designed for "OS as appliance" model

### Nomad

- Good workload scheduler, simpler than Kubernetes
- Supports multiple runtimes (containers, Java, raw exec, WASM via drivers)
- **Cannot manage host OS primitives** — no firewall, disk, or sysctl management
- Designed for clusters, heavyweight for single-node

### k3s / Kubernetes

- Can do everything (workloads + NetworkPolicy + storage classes)
- **Massive complexity overhead** — etcd, API server, kubelet, CRDs, operators
- Overkill for single-node or small deployments
- Steep learning curve

### Talos OS

- Closest to what we want — API-driven, no SSH, declarative machine config
- Has a Terraform provider (`siderolabs/talos`)
- **But requires Kubernetes** for all workloads — can't just run a Compose-like stack
- Building a new OS is a multi-year, multi-team effort — we should not compete here

### NixOS

- Single `configuration.nix` declares everything (OS + apps + firewall + services)
- Atomic upgrades and rollbacks
- **But**: Nix language has a steep learning curve, ecosystem is niche
- Not API-driven (requires SSH or local access to rebuild)
- No Terraform provider for runtime changes

### cloud-init / Ignition

- Good for OS config at boot time
- **One-shot only** — no continuous convergence
- No application deployment
- No runtime API

### Salt (SaltStack)

- Has a daemon + REST API (salt-api)
- Can manage both OS and apps
- **Requires Python + Salt minion** on every node — heavy runtime dependency
- Complex, declining community

---

## Prior Art: Lessons from rust-ansible

This project started as `rust-ansible` — an attempt to embed Ansible inside a WASM
binary using WASIX Python + Wasmer. Key learnings:

### What We Tried

Embedded CPython (compiled to WASIX) + ansible-core 2.20.2 into a single Rust binary
using Wasmer 7.0. Created extensive compatibility stubs to patch missing WASI primitives.

### What Worked

- WASIX Python 3.13 runs in Wasmer with threading support
- Ansible imports successfully with patches
- Playbook parsing and inventory loading work
- A custom `wasi_local` connection plugin executes modules in-process via `exec()`
- The `ping` module returns `{"ping": "pong"}` successfully

### What We Learned

1. **Ansible fundamentally depends on OS primitives** — subprocess, fork, SSH, signals,
   privilege escalation. Sandboxing it in WASM means stubbing out half the OS.
   The result — localhost-only, no fact gathering, no become, no subprocess — is not
   really "Ansible." It's a narrow subset.

2. **WASM is wrong for running legacy apps.** Trying to run complex existing software
   (Ansible, Jira, Postgres) inside WASM means fighting the entire POSIX ecosystem.
   WASM requires everything to be recompiled. Language toolchain support varies widely.
   Containers run existing software unchanged — that's why Docker won.

3. **WASM is right for the control plane.** Where WASM excels: sandboxed execution,
   capability-based security, portability, instant startup, polyglot composition.
   These properties are ideal for **management/control logic**, not for running
   arbitrary legacy applications.

4. **The maintenance burden is real.** 13KB of monkey-patching (wasi_bootstrap.py),
   custom connection plugin, multiprocessing stubs, fcntl stubs, pwd/grp stubs.
   Every Ansible version bump could break any of these.

5. **Wasmer requires Rust nightly.** Wasmer 7.0 needs Rust 1.91+. WASIX is a
   Wasmer-proprietary extension (not a WASI standard). This is vendor lock-in.

6. **20+ minute first-run compilation.** Cranelift compiling 10.5 MB Python WASM is
   extremely slow. Pre-compiled module caching exists but is fragile.

### The Pivot

Instead of fighting gravity by putting Ansible inside WASM, **combine WASM (for the
control plane and lightweight workloads) with containers (for existing/heavy apps)**.
The insight: use each technology where it's strong.

### Files from rust-ansible

The previous implementation lives in this repository:

- `src/main.rs` — Rust Wasmer embedding (387 lines)
- `assets/stubs/` — WASI compatibility layer
- `Cargo.toml`, `Cargo.lock` — Rust dependencies
- `FEASIBILITY.md` — WASI Python feasibility report
- `PROGRESS.md` — rust-ansible progress tracking
- `PROMPT.md` — Original project prompt
- `tests/` — 23 ad-hoc test scripts

These can be archived or used as reference. The new project will be built fresh.

---

## Product Definition

### One-Liner

A WASM-native node runtime that manages containers and OS primitives through a single
declarative config, secured by capability-based sandboxing, driven by API.

### What It Is

- A **single Rust binary** that runs on any Linux node
- Combines a **WASM runtime** (Wasmtime) with a **minimal container runtime** (containerd + Youki)
- Manages **workloads** (containers, and eventually WASM modules) and **OS primitives**
  (firewall, disks, mounts, systemd units) from one config
- **API-driven** — gRPC/HTTP endpoint, no SSH needed
- **Continuously converges** toward desired state (detects and reverts drift)
- **Secure by default** — capabilities only granted based on what's declared in config
- **Hot-reloadable** — config changes apply without stopping running services

### What It Is Not

- Not a cluster orchestrator (not replacing Kubernetes/Nomad for multi-node scheduling)
- Not a custom OS (runs on any Linux — Flatcar, Ubuntu, RHEL, etc.)
- Not a container runtime replacement (uses containerd/Youki under the hood)
- Not trying to run legacy apps as WASM (containers handle that)

### Target Users

- Engineers running **single-node or small-fleet deployments** on immutable/minimal OSes
- Teams using **Flatcar/Talos/Bottlerocket** who want something lighter than Kubernetes
- **Edge/IoT deployments** where k3s is too heavy and Docker Compose is too manual
- Companies shipping **appliance-like products** (hardware + software)
- Anyone who wants **Terraform/Pulumi-driven node configuration** without SSH

---

## Architecture

```
                  ┌─────────────────────────────────────────┐
                  │  User / Terraform Provider              │
                  └──────────────┬──────────────────────────┘
                                 │ gRPC / HTTP API
                  ┌──────────────▼──────────────────────────┐
                  │  Agent (single Rust binary)              │
                  │                                          │
                  │  ┌──────────────────────────────────┐   │
                  │  │  Config Engine                    │   │
                  │  │  ├── YAML parser (serde)          │   │
                  │  │  ├── Desired state derivation     │   │
                  │  │  ├── Capability calculator         │   │
                  │  │  └── Hot reload (inotify watch)   │   │
                  │  └──────────────────────────────────┘   │
                  │                                          │
                  │  ┌──────────────────────────────────┐   │
                  │  │  Reconciliation Loop              │   │
                  │  │  ├── Diff desired vs actual       │   │
                  │  │  ├── Converge toward desired      │   │
                  │  │  └── Poll interval (configurable) │   │
                  │  └──────────────────────────────────┘   │
                  │                                          │
                  │  ┌──────────────────────────────────┐   │
                  │  │  OS Primitive Modules (WASM)      │   │
                  │  │  ├── firewall.wasm → nftables     │   │
                  │  │  ├── disk.wasm → mount/mkfs       │   │
                  │  │  ├── systemd.wasm → unit files    │   │
                  │  │  ├── user.wasm → useradd/mod      │   │
                  │  │  └── sysctl.wasm → /proc/sys      │   │
                  │  │  (Wasmtime runtime)               │   │
                  │  └──────────────────────────────────┘   │
                  │                                          │
                  │  ┌──────────────────────────────────┐   │
                  │  │  Container Backend                │   │
                  │  │  ├── containerd (image pulls,     │   │
                  │  │  │   networking, volumes)          │   │
                  │  │  └── Youki (OCI runtime)           │   │
                  │  └──────────────────────────────────┘   │
                  │                                          │
                  │  ┌──────────────────────────────────┐   │
                  │  │  WASM Workload Runtime (Phase 2)  │   │
                  │  │  └── Wasmtime for .wasm workloads │   │
                  │  └──────────────────────────────────┘   │
                  │                                          │
                  └──────────────────────────────────────────┘
                                     │
                  ┌──────────────────▼──────────────────────┐
                  │  Linux (Flatcar / Ubuntu / RHEL / etc.) │
                  └─────────────────────────────────────────┘
```

### Component Responsibilities

**Config Engine**: Parses YAML, derives desired state, calculates what capabilities are
needed (from config sections present), triggers reconciliation on changes.

**Reconciliation Loop**: Periodically compares desired state to actual state. Applies
changes to converge. Detects drift and reverts. Configurable poll interval.

**OS Primitive Modules**: WASM components loaded by the agent, each responsible for one
OS domain (firewall, disks, etc.). Sandboxed — each module can only access the host
interfaces it's granted. Swappable per OS variant.

**Container Backend**: containerd handles higher-level container management (image pulls,
networking, volumes, lifecycle). Youki is the OCI runtime that actually runs containers.
The agent talks to containerd, containerd talks to Youki.

**WASM Workload Runtime** (Phase 2): Optional WASM workload execution alongside
containers. For lightweight services that don't need a full container.

---

## Technology Choices and Rationale

### Rust (for the agent binary)

**Why**: Systems language, single static binary output, strong ecosystem for WASM
(Wasmtime is Rust-native), no runtime dependencies, excellent performance.

**Alternatives considered**:
- Go: Good for systems tools, has wazero for WASM. Viable alternative, but Wasmtime's
  Rust API is more mature than any Go WASM runtime.
- C/C++: Too much manual memory management for this scope.

### Wasmtime (for WASM runtime)

**Why**: Bytecode Alliance project (Mozilla, Fastly, Intel, Red Hat). Works on stable
Rust. Production-proven (used by Fastly, Shopify, Fermyon). Best WASI standards
compliance. Component Model support.

**Why NOT Wasmer**: Requires Rust nightly. WASIX is proprietary (not WASI standard).
We learned this the hard way in the rust-ansible phase.

**Why NOT wazero**: Go-only. If we're writing in Rust, Wasmtime is the natural choice.

### containerd + Youki (for containers)

**Why containerd**: Handles all higher-level container management — image pulls from
registries, container networking (CNI), volume management, image layer unpacking,
container lifecycle. Used by Kubernetes, k3s, and Nomad under the hood. Battle-tested.

**Why Youki**: Rust-native OCI runtime. Keeps the entire stack in Rust. OCI-compliant,
so it's a drop-in replacement for runc under containerd.

**Why NOT Youki alone**: Youki is a low-level OCI runtime. It runs containers given a
prepared bundle. It does NOT handle image pulls, networking, volumes, or lifecycle.
Building all of that from scratch would take months. containerd provides it.

**Why NOT Podman**: Podman could work for v1 (it's simpler), but containerd gives more
control for the long term and is more composable as a library.

### nftables (for firewall management)

**Why**: Modern Linux firewall subsystem, replaces iptables. Consistent API.
Available on all recent Linux distributions and immutable OSes.

### YAML (for config format)

**Why**: Familiar to anyone who's used Docker Compose, Kubernetes, Ansible, or any
modern DevOps tool. Low barrier to adoption.

---

## WASM Benefits and Limitations

### Why WASM for OS Primitive Modules

The agent manages OS primitives (firewall, disks, etc.) through WASM modules rather than
hardcoded Rust code. This provides:

#### 1. Capability-Based Security (Deny-by-Default)

WASM modules start with zero capabilities. They cannot access filesystem, network, or
any OS resource unless the host explicitly grants it. This is fundamentally different
from containers (which start with most Linux capabilities and try to drop them).

A firewall module gets `host:nftables` interface. It literally cannot touch the
filesystem, read environment variables, or access anything else. The sandbox is the
security boundary — no RBAC needed.

#### 2. True Portability

Same `.wasm` binary runs on x86, ARM, RISC-V, on Linux, macOS, Windows, FreeBSD.
One artifact, no multi-arch builds.

#### 3. Isolation of OS-Specific Code

Different firewall module for nftables vs iptables-legacy. Different disk module for
LVM vs ZFS. The agent core stays the same; modules are swapped. This is how multi-OS
support works without forking the agent.

#### 4. Safe Extensibility

Users can write custom modules in any language that compiles to WASM (Rust, Go, C,
Python, etc.) and load them. The WASM sandbox means user-defined modules cannot break
the agent or access OS resources beyond their granted capabilities.

#### 5. Independent Updates

Update a firewall module without rebuilding the entire agent. WASM modules are small
(KB-MB range) and can be pulled from a registry.

### Where WASM Is NOT Used

**Running legacy applications.** Jira, Postgres, Redis, Nginx — these run as containers.
WASM cannot run existing binaries without recompilation, and many languages lack mature
WASM server-side toolchains (Java, Ruby, .NET).

**The agent itself.** The agent is a native Rust binary. It needs real OS access to
manage the WASM runtime, talk to containerd, and expose host capabilities. The agent is
the trust boundary.

### WASM Technical Properties

| Property | Value |
|---|---|
| Startup time | ~1-10 ms (vs 1-10 seconds for containers) |
| Memory per instance | 1-64 MB (vs 50-500 MB for containers) |
| Module size | 1-10 MB (vs 50 MB - 1 GB for container images) |
| Performance overhead | 1.2-2x vs native |
| Security model | Deny-by-default, capability-based |
| Language support | Rust, C, C++ (excellent), Go/TinyGo (good), Python (experimental) |
| Composability | Component Model — cross-language function calls, zero serialization |

---

## Security Model: Config-Driven Capabilities

### Core Principle

**The config IS the permission manifest.** If a config section doesn't exist, the
corresponding capability is never granted, and the corresponding WASM module is never
even loaded.

### How It Works

```
Agent starts → reads config.yaml
  ├── Config has `firewall:` section?
  │   YES → load firewall.wasm, grant host:nftables interface
  │   NO  → firewall module never instantiated, nftables unreachable
  │
  ├── Config has `workloads:` section?
  │   YES → initialize containerd connection, grant host:container interface
  │   NO  → container runtime never started
  │
  ├── Config has `disks:` section?
  │   YES → load disk.wasm, grant host:mount + host:mkfs interface
  │   NO  → disk module never instantiated
  │
  └── (and so on for each OS primitive)
```

### WASM Import-Level Enforcement

A WASM module declares what host functions it needs as imports. If the host doesn't
provide them, the module can't call them. This isn't "blocked" — the functions are
literally nonexistent in the module's address space. There's no escape hatch.

```rust
// The host decides exactly what a module can access
let firewall_module = Module::from_file(&engine, "firewall.wasm")?;

// This instance can ONLY call nftables host functions. Nothing else.
let instance = linker
    .func_wrap("host", "nftables_add_rule", |rule: &str| { ... })?
    .func_wrap("host", "nftables_delete_rule", |rule: &str| { ... })?
    .func_wrap("host", "nftables_list_rules", || { ... })?
    .instantiate(&mut store, &firewall_module)?;
```

### Trust Boundaries

```
Untrusted:
  └── WASM modules (sandboxed, capability-limited)

Trusted:
  ├── Agent binary (native Rust, runs as root/privileged)
  ├── containerd (manages containers)
  └── Youki (OCI runtime)
```

The agent itself runs privileged (it needs root for nftables, mounts, containers). But
the WASM modules can only reach the OS through the specific host functions the agent
exposes. The agent is the sole trust boundary.

---

## Hot Reload Design

### Requirements

- Config changes apply without stopping unaffected running services
- Permission model can change on config updates
- New sections can be added (grant new capabilities)
- Sections can be removed (revoke capabilities)

### Mechanism

1. Agent watches config file via `inotify` (Linux) or polling
2. On change: parse new config, validate, diff against current state
3. Apply changes incrementally:

**For workloads:**
- New workload in config → pull image, start container
- Workload removed from config → stop and remove container
- Workload config changed → recreate container (like `docker compose up -d`)
- Workload unchanged → do nothing (container keeps running)

**For OS primitives:**
- New section (e.g., `firewall:` added) → load WASM module, grant capabilities,
  converge toward desired state
- Section removed → **policy decision** (see below)
- Section changed → update desired state, let reconciliation converge

**For WASM modules:**
- WASM modules are cheap to restart (~milliseconds)
- On capability change: terminate old module instance, create new one with updated
  capabilities
- Module state is derived from config, so restart is safe

### Section Removal Policy

When a config section is removed, three options exist:

1. **Revert to OS default** — undo all rules the agent applied. Clean but "default"
   varies by OS.
2. **Leave as-is** — stop managing, keep current state. Safe but drift undetectable.
3. **Require explicit removal** — force `firewall: reset` or `firewall: disabled`.

**Decision for v1**: Option 3 (require explicit removal). Removing a section means
"stop managing this, leave it alone." Explicit `reset` or `disabled` value means "undo
my rules." No accidental state changes.

---

## Convergence Loop

### Design

```
loop {
    desired_state = parse_config(config_file)
    actual_state = collect_actual_state()
    diff = compute_diff(desired_state, actual_state)

    if diff.is_empty() {
        // All converged, nothing to do
    } else {
        for change in diff {
            apply_change(change)  // idempotent
        }
    }

    sleep(poll_interval)  // default: 30s
}
```

### State Collection

**Container state**: Query containerd API — which containers are running, their images,
ports, volumes, health status.

**Firewall state**: Query nftables — current rules, compare with desired rules.

**Disk state**: Check mount table — what's mounted where, filesystem types.

### Idempotent Operations

All convergence operations must be idempotent. Running the same desired state twice
produces the same result. This means:
- "Ensure container X is running" → check if running, start only if not
- "Ensure firewall rule Y exists" → check if exists, add only if not
- "Ensure disk Z is mounted at /data" → check if mounted, mount only if not

### Drift Detection

Drift = someone or something changed actual state outside the agent. The convergence
loop detects this naturally — actual state diverges from desired, agent corrects it.

Example: someone manually adds a firewall rule. Next convergence cycle, agent sees rules
don't match desired state, reverts to desired state. This is continuous convergence,
not one-shot.

---

## MVP Scope

### In Scope (v0.1)

**Core agent:**
- Single Rust binary
- YAML config parser (serde + custom schema)
- Reconciliation loop (poll-based, configurable interval)
- Hot reload (inotify config file watch)
- HTTP API (basic — apply config, get status)

**Container management:**
- Manage containers via containerd + Youki
- Pull images from registries
- Port mapping
- Volume mounts
- Health checks (HTTP)
- Restart policies
- Service dependencies (start order)

**One OS primitive — firewall (nftables):**
- Proves the OS management pattern
- Hardcoded in Rust for v1 (not yet WASM modules — save that for v0.2)
- Default deny policy
- Ingress rules by port + source CIDR

**Config-driven capabilities:**
- No `firewall:` section → firewall management code never runs
- No `workloads:` section → containerd never initialized

### Out of Scope for v0.1

- WASM modules for OS primitives (hardcode in Rust for v1)
- WASM as a workload runtime (Phase 2)
- Terraform provider (Phase 2)
- gRPC API (HTTP is simpler for v1)
- Disk management, user management, sysctl, systemd units
- Container networking beyond basic bridge
- Secrets management
- TLS on the API
- Multi-node / clustering
- Non-Linux support

### The MVP Demo

```yaml
# config.yaml
workloads:
  nginx:
    image: nginx:latest
    ports: ["80:80", "443:443"]
    volumes:
      - ./html:/usr/share/nginx/html:ro
    healthcheck:
      url: http://localhost:80
      interval: 30s
    restart: always

system:
  firewall:
    default: deny
    ingress:
      - { port: 80, allow: 0.0.0.0/0 }
      - { port: 443, allow: 0.0.0.0/0 }
      - { port: 22, allow: 10.0.0.0/8 }
```

```bash
# One command, one config, one binary
$ myagent apply config.yaml

# Agent:
# 1. Reads config -> needs container + firewall capabilities
# 2. Converges firewall rules via nftables
# 3. Pulls nginx image, starts container via containerd/youki
# 4. Enters reconciliation loop
# 5. Watches config file for changes

# Someone manually deletes the firewall rule:
$ nft flush ruleset
# -> Agent detects drift, restores rules within 30 seconds

# Update config to add a port:
$ vim config.yaml  # add port 8080
# -> Agent hot-reloads, adds firewall rule, no container restart
```

---

## Future Phases

### Phase 2: WASM Modules + Terraform (v0.2)

- Extract OS primitives into WASM modules (firewall.wasm, disk.wasm, etc.)
- Add disk management (mount, mkfs, fstab)
- Add systemd unit management
- WASM workload runtime alongside containers (run .wasm workloads)
- Terraform provider for the API
- gRPC API (replace or supplement HTTP)
- TLS / mTLS on the API

### Phase 3: Extensibility + Multi-OS (v0.3)

- User-defined WASM modules (custom OS primitives, custom health checks)
- Module registry (pull modules from OCI registry)
- Second OS target (e.g., Ubuntu) — proves WASM module swapping works
- User/group management module
- sysctl management module
- Certificate management module
- Secrets management (integrate with external secrets stores)

### Phase 4: Multi-Node + Production Hardening (v1.0)

- Multi-node coordination (optional — for small clusters)
- Audit logging
- RBAC for API access
- Backup/restore of agent state
- Upgrade/rollback mechanism for the agent itself
- Comprehensive test suite and CI/CD

---

## Open Questions and Risks

### Open Design Questions

1. **Naming**: The project needs a name. The repo is currently `go-ansible` which is
   entirely wrong. Needs something that conveys "node runtime" or "workload + OS manager."

2. **API authentication**: How is the API secured? mTLS? API tokens? For v1, the API
   could be localhost-only (Unix socket), with remote access deferred.

3. **Container networking model**: Basic bridge networking for v1? CNI plugins? How do
   containers communicate with each other?

4. **State storage**: Where does the agent store its own state (what it's managing,
   previous config, etc.)? SQLite? Flat files? In-memory only?

5. **Init system integration**: Should the agent manage itself as a systemd service?
   How does it start on boot? Ignition/cloud-init can install it.

6. **Config delivery**: v1 uses a local file. For fleet management, how is config
   delivered? Git-based (GitOps)? API push? Pull from a central server?

7. **Logging and observability**: Structured logging (JSON)? Integration with
   journald? Prometheus metrics endpoint?

### Technical Risks

1. **containerd Go client API surface**: The containerd Go client is well-documented
   for basic operations (pull, create, start, stop). More advanced features (networking
   setup, port mapping) may require additional libraries or lower-level plumbing.
   Investigate how nerdctl (containerd's Docker-compatible CLI, also Go) handles these.

2. **containerd as external dependency**: Requires containerd daemon running. On Flatcar,
   it's pre-installed. On other distros, it's an install step. For the future, k3s and
   k0s demonstrate that containerd can be embedded as a Go library — investigate their
   `pkg/agent/containerd` and embedding approach if "truly single binary" becomes needed.

3. **google/nftables library completeness**: The library talks to the kernel via netlink.
   Need to verify it supports all rule types we need (CIDR matching, port ranges,
   connection tracking). Fallback: shell out to `nft` command for edge cases.

4. **Hot reload complexity**: Diffing container state and OS state, then applying
   minimal changes without disruption, is non-trivial. The reconciliation loop is
   conceptually simple but has many edge cases (e.g., container image changed but
   volumes unchanged — recreate or update in place?).

5. **Scope creep**: The system has many potential features. Discipline is needed to
   ship a minimal v0.1 that proves the concept. Start with containers + firewall only.

### Strategic Risks

1. **Talos adds non-Kubernetes workloads**: If Talos adds Compose-like workload
   support, the gap we're filling closes.

2. **Nomad adds host management**: If HashiCorp extends Nomad to manage OS primitives,
   our differentiation narrows.

3. **Docker Compose gets an API**: Docker could add an API layer and OS management
   to Compose. Unlikely given Docker's direction, but possible.

4. **Adoption**: The target audience (single-node / small-fleet on immutable OS) is
   real but niche. Needs to expand to general Linux servers for meaningful adoption.

---

## Strategic Context

### The Bigger Picture

This project serves a larger goal: demonstrating that **WASM can be a practical
infrastructure primitive** — not by replacing containers entirely, but by providing
value where containers can't:

- **Sandboxed, capability-based OS management** (vs Ansible's "Python with root")
- **Polyglot extensibility** (write modules in any language → WASM)
- **Portable control plane** (same agent logic runs on any architecture)
- **Composable modules** (WASM Component Model for cross-language composition)

Containers handle what they're good at: running existing Linux applications unchanged.
WASM handles what it's good at: sandboxed, portable, lightweight control logic.

### The Adoption Path

```
Phase 1: "Simpler alternative to k3s for single-node"
  → Engineers adopt for simple deployments on Flatcar/minimal OSes

Phase 2: "Extensible with WASM modules"
  → Community writes modules for various OS primitives and integrations

Phase 3: "Run WASM workloads alongside containers"
  → New applications written WASM-first, container footprint shrinks

Phase 4: "The industry standard for WASM + container hybrid runtime"
  → WASM becomes a mainstream workload runtime, not just a plugin system
```

### The One-Sentence Pitch for Each Audience

**For DevOps engineers**: "One config file for your app AND your firewall — no
Kubernetes, no SSH, no YAML hell."

**For platform teams**: "A programmable node runtime you can extend with WASM modules
instead of writing Kubernetes operators."

**For the WASM ecosystem**: "A production use case for WASM beyond serverless — managing
real infrastructure with capability-based security."

---

## Plan B: Compose + CM Agent (No WASM)

### Rationale

Plan A (WASM-native runtime) is the strategic vision, but it carries technical risk:
Wasmtime integration, WASM module development, Component Model maturity, and the extra
complexity of a WASM-based module system. If that risk proves too high — or if we simply
want to **ship something useful faster** — Plan B strips out WASM entirely and focuses
on the core value proposition:

> **A zero-dependency Docker Compose alternative that also continuously converges OS
> state. One binary. One config. Compose + configuration management agent in a single
> executable.**

The key insight: **WASM is not what makes this product valuable.** The value is the
unified config for workloads + OS primitives, continuous convergence, and the API. WASM
is an implementation detail for extensibility — nice to have, not essential for v1.

### Language: Go

Plan B uses **Go** instead of Rust. Rationale:

- The entire container infrastructure ecosystem is Go — containerd, Docker, Kubernetes,
  Nomad, Terraform, Prometheus. We swim with the current, not against it.
- **containerd is a Go project** — its client library
  (`github.com/containerd/containerd/v2/client`) is first-class Go, no FFI/bindings.
- Every OS primitive library we need has a mature, production-proven Go implementation:

| Need | Go Library | Maintainer |
|------|------------|------------|
| Container management | `github.com/containerd/containerd/v2/client` | CNCF / containerd team |
| nftables firewall | `github.com/google/nftables` | Google (netlink-based, no shell-out) |
| systemd units | `github.com/coreos/go-systemd/v22` | CoreOS / Red Hat (D-Bus native) |
| YAML config | `gopkg.in/yaml.v3` | Canonical |
| File watching | `github.com/fsnotify/fsnotify` | Well-maintained community |
| HTTP API | `net/http` (stdlib) | Go team |
| gRPC API (future) | `google.golang.org/grpc` | Google |

- Faster development cycle than Rust (no borrow checker overhead for a tool like this)
- Single static binary via `CGO_ENABLED=0 go build`
- Goroutines are a natural fit for reconciliation loop, file watching, and API server
- Easier to attract contributors (Go is the expected language for infra tooling)

**Path to Plan A (WASM) stays open.** If Plan B succeeds and WASM extensibility is
needed, **wazero** is a pure-Go WASM runtime (no CGO, no Rust dependency). The
`SystemModule` interface (see below) becomes the WASM module boundary. Same language
throughout — no rewrite needed.

### Architecture (Plan B)

```
                  ┌─────────────────────────────────────────┐
                  │  User / Terraform Provider              │
                  └──────────────┬──────────────────────────┘
                                 │ HTTP API
                  ┌──────────────▼──────────────────────────┐
                  │  Agent (single Go binary, ~15-20 MB)    │
                  │                                          │
                  │  ┌──────────────────────────────────┐   │
                  │  │  Config Engine                    │   │
                  │  │  ├── YAML parser (gopkg.in/yaml)  │   │
                  │  │  ├── Desired state derivation     │   │
                  │  │  └── Hot reload (fsnotify)        │   │
                  │  └──────────────────────────────────┘   │
                  │                                          │
                  │  ┌──────────────────────────────────┐   │
                  │  │  Reconciliation Loop (goroutine)  │   │
                  │  └──────────────────────────────────┘   │
                  │                                          │
                  │  ┌──────────────────────────────────┐   │
                  │  │  OS Modules (native Go)           │   │
                  │  │  ├── firewall (google/nftables)   │   │
                  │  │  ├── disks (mount/mkfs syscalls)  │   │
                  │  │  ├── systemd (go-systemd/dbus)    │   │
                  │  │  └── sysctl (/proc/sys writes)    │   │
                  │  └──────────────────────────────────┘   │
                  │                                          │
                  │  ┌──────────────────────────────────┐   │
                  │  │  Container Backend                │   │
                  │  │  └── containerd client (Go API)   │   │
                  │  └──────────────────────────────────┘   │
                  │                                          │
                  └──────────────────────────────────────────┘
                                     │ containerd socket
                  ┌──────────────────▼──────────────────────┐
                  │  containerd (external daemon)           │
                  │  └── runc / youki (OCI runtime)         │
                  ├──────────────────────────────────────────┤
                  │  Linux (any distro)                     │
                  └─────────────────────────────────────────┘
```

### containerd: External Dependency (For Now)

containerd is the **sole external dependency**. The agent binary talks to containerd
over its Unix socket. containerd handles image pulls, container networking, storage,
and lifecycle — delegating actual container execution to runc or Youki.

**Why not embed containerd?** Both k3s and k0s embed containerd into their single binary.
This is technically possible — containerd is Go, so it can be imported as a library and
run in-process. However:

- Embedding containerd is significant engineering effort (k3s has extensive plumbing)
- It balloons the binary from ~15-20 MB to ~50-60 MB
- It provides no benefit for the MVP — we need to validate the product first
- containerd is pre-installed on Flatcar and trivially installable elsewhere

**For v0.1**: Require containerd as an external daemon. Focus on the actual differentiator.

**For the future**: Investigate k3s's `pkg/agent/containerd` and k0s's embedding approach.
If "truly single binary" becomes a user demand, embed containerd the same way they do.
This is a packaging concern, not an architectural one — the agent talks to containerd
the same way whether it's external or embedded.

### What Changes from Plan A

| Aspect | Plan A (Rust + WASM) | Plan B (Go, No WASM) |
|--------|---------------------|---------------------|
| Language | Rust | Go |
| OS modules | WASM components via Wasmtime | Native Go code, compiled into binary |
| Extensibility | User-defined WASM modules in any language | Go-only, requires recompilation (wazero for future WASM) |
| Security model | WASM sandbox enforces capability isolation | Process-level — agent runs privileged, modules are Go functions with no sandbox boundary |
| Multi-OS support | Swap WASM modules per OS | Build tags or runtime detection |
| Binary size | ~20-30 MB (Wasmtime adds ~10-15 MB) | ~15-20 MB |
| Dependencies | Wasmtime (embedded) + containerd | containerd only |
| Complexity | Higher (WASM host functions, Component Model) | Lower (straightforward Go) |
| Time to MVP | ~3-4 months | ~1-2 months |
| Ecosystem fit | Rust WASM ecosystem | Go infra ecosystem (containerd, nftables, systemd — all native) |

### What Stays the Same

Everything the user cares about is identical:

- **Same YAML config format** — workloads + system sections
- **Same reconciliation loop** — continuous convergence, drift detection
- **Same hot reload** — config changes apply without restarting services
- **Same API** — HTTP endpoint for apply/status, future Terraform provider
- **Same container management** — containerd + Youki, Compose-like experience
- **Same OS primitives** — firewall, disks, systemd, sysctl
- **Same section removal policy** — explicit `disabled`/`reset` required

### Plan B Config (Identical to Plan A)

```yaml
workloads:
  jira:
    image: atlassian/jira-software:9.12
    ports: ["8080:8080"]
    volumes:
      - /data/jira:/var/atlassian/application-data/jira
    healthcheck:
      url: http://localhost:8080/status
      interval: 60s
    restart: always
    depends_on: [postgres]

  postgres:
    image: postgres:16
    volumes:
      - /data/postgres:/var/lib/postgresql/data
    environment:
      POSTGRES_DB: jira
      POSTGRES_USER: jira
      POSTGRES_PASSWORD: "${JIRA_DB_PASSWORD}"
    restart: always

system:
  firewall:
    default: deny
    ingress:
      - { port: 8080, allow: 0.0.0.0/0 }
      - { port: 22, allow: 10.0.0.0/8 }
    egress:
      default: allow

  disks:
    - device: /dev/sdb
      filesystem: ext4
      mount: /data
      options: [noatime]

  sysctl:
    vm.swappiness: 10
    net.core.somaxconn: 65535
```

### Plan B Advantages

1. **Ships faster.** No WASM runtime, no module interface design, no Component Model
   complexity. Straightforward Go with battle-tested libraries.

2. **Ecosystem alignment.** containerd, nftables, systemd — all have first-class Go
   libraries maintained by Google, Red Hat, and the CNCF. No bindings, no FFI, no
   shelling out.

3. **Fewer moving parts.** The only external dependency is containerd. No WASM runtime
   to debug, no module loading, no host function interfaces.

4. **Easier to understand and contribute to.** OS modules are Go interfaces. The infra
   community already knows Go — lower barrier to contributions than Rust.

5. **Proves the value proposition faster.** If nobody wants "Compose + CM agent," it
   doesn't matter how elegant the WASM architecture is. Ship the simple version, see if
   it resonates, add WASM later if it does.

### Plan B Disadvantages

1. **No sandboxing between modules.** A bug in the firewall module can crash the entire
   agent. In Plan A, a WASM module crash is isolated.

2. **Not extensible by users at runtime.** Adding a new OS primitive means modifying
   the agent's Go code and recompiling. In Plan A, users drop in a `.wasm` file.
   (Mitigated: wazero can be added later for runtime extensibility.)

3. **Multi-OS support is harder.** Different OS modules need Go build tags or runtime
   branching. In Plan A, you swap a WASM module.

4. **Doesn't advance the WASM thesis.** Plan B is useful but conventional. It doesn't
   demonstrate WASM's value as an infrastructure primitive.

5. **Harder to evolve into Plan A later.** If OS modules are tightly coupled Go code,
   extracting them into WASM modules later requires refactoring. Mitigated by designing
   a clean interface from the start (see below).

### Plan B Module Interface (Designed for Future WASM Extraction)

Even in Plan B, OS modules should implement a Go interface that mirrors what a WASM
module boundary would look like. This makes future extraction to WASM via wazero
feasible without an architectural rewrite:

```go
// SystemModule is the interface every OS module implements.
// In Plan B: implemented directly in Go.
// In Plan A: this becomes the WASM module boundary (via wazero).
type SystemModule interface {
    // SectionName returns the config section this module manages (e.g., "firewall")
    SectionName() string

    // ParseConfig derives desired state from the config section
    ParseConfig(cfg map[string]any) (DesiredState, error)

    // CollectState reads actual state from the OS
    CollectState() (ActualState, error)

    // Converge computes and applies changes to reach desired state
    Converge(desired DesiredState, actual ActualState) (Changes, error)

    // Revert undoes all managed state (for `reset`/`disabled`)
    Revert() error
}

// Example: firewall module using google/nftables
type NftablesModule struct {
    conn *nftables.Conn
}

func (m *NftablesModule) SectionName() string { return "firewall" }

func (m *NftablesModule) CollectState() (ActualState, error) {
    // Query nftables via netlink for current rules
    chains, err := m.conn.ListChains()
    // ...
}

func (m *NftablesModule) Converge(desired DesiredState, actual ActualState) (Changes, error) {
    // Diff rules, add missing, remove extra, flush to kernel
    // ...
}
```

This interface is the **migration path** from Plan B to Plan A. When WASM is added
later (via wazero), each `SystemModule` implementation becomes a WASM component that
exports the same interface. The agent's reconciliation loop doesn't change — it calls
the same methods regardless of whether the module is native Go or WASM.

### Plan B MVP Scope

Identical to Plan A's MVP scope (see [MVP Scope](#mvp-scope)), minus anything
WASM-related:

- Single Go binary (`CGO_ENABLED=0 go build`)
- YAML config parser (`gopkg.in/yaml.v3`)
- containerd (external daemon) for container management
- Firewall management (nftables) — native Go module using `google/nftables`
- Reconciliation loop with drift detection (goroutine, configurable interval)
- Hot reload via `fsnotify`
- HTTP API (apply config, get status) — `net/http` stdlib
- Config-driven: no `firewall:` section → firewall code never runs

### Plan B Proposed Project Structure

```
cmd/
  agent/
    main.go                  # Entry point, CLI flags, signal handling
internal/
  config/
    config.go                # YAML parsing, validation, diffing
    types.go                 # Config struct definitions
  reconciler/
    reconciler.go            # Main reconciliation loop
    diff.go                  # Desired vs actual state diffing
  modules/
    module.go                # SystemModule interface definition
    firewall/
      nftables.go            # nftables implementation
    disk/                    # (Phase 2)
    systemd/                 # (Phase 2)
    sysctl/                  # (Phase 2)
  containers/
    manager.go               # containerd client wrapper
    types.go                 # Container desired/actual state types
  api/
    server.go                # HTTP API endpoints
    handlers.go              # apply, status, health handlers
go.mod
go.sum
config.example.yaml
```

### Plan B Phases

**Phase 1 (v0.1)**: Core agent + containers + firewall. Same demo as Plan A.
Go binary, containerd dependency, nftables via `google/nftables`, reconciliation loop.

**Phase 2 (v0.2)**: Disk management, systemd units (`go-systemd`), sysctl.
Terraform provider. TLS on API.

**Phase 3 (v0.3)**: Evaluate WASM extensibility. If needed, add wazero and extract OS
modules behind the `SystemModule` interface into WASM components. This is where Plan B
converges back into Plan A — but only if the product has proven itself and runtime
extensibility is actually demanded by users.

### Recommendation

**Start with Plan B. Migrate to Plan A if the product resonates.**

The risk of Plan A is building a complex WASM architecture for a product nobody uses.
The risk of Plan B is shipping something useful but conventional. Plan B's risk is
cheaper — a useful tool that lacks WASM is better than a WASM showcase that nobody
adopts.

The Go `SystemModule` interface ensures that the migration path from Plan B → Plan A
exists. When WASM is needed, wazero (pure Go, no CGO) plugs in behind the same
interface. No language switch, no rewrite — just a new implementation of `SystemModule`
that delegates to WASM.

Plan A remains the strategic north star. Plan B is the pragmatic path to get there.

**Decision**: Plan B is the active implementation plan. Go + containerd (external) +
native OS modules. Single external dependency. Ship fast, validate the concept.

---

## Previous Work Reference

### Repository Structure (current — to be archived/restructured)

```
/home/denys/go-ansible/
├── src/main.rs                   # Rust Wasmer embedding (rust-ansible)
├── assets/stubs/                 # WASI compatibility layer (rust-ansible)
├── Cargo.toml, Cargo.lock        # Rust dependencies (rust-ansible)
├── tests/                        # Ad-hoc test scripts (rust-ansible)
├── PLAN.md                       # This file
├── FEASIBILITY.md                # WASI Python feasibility report
├── PROGRESS.md                   # rust-ansible progress tracking
├── PROMPT.md                     # Original go-ansible prompt
├── test_playbook.yml             # Sample Ansible playbook
├── inventory.ini                 # Ansible inventory
├── LICENSE                       # MIT license
└── .mise.toml                    # Tool management
```

### Key Documents

- **FEASIBILITY.md**: Detailed report on running CPython + Ansible under WASI.
  Concluded "NO-GO for full ansible-core under standard WASI Python" but identified
  WASIX as a viable alternative (which was then implemented in rust-ansible).

- **PROGRESS.md**: Tracks rust-ansible implementation. Phase 1 (stubs) and Phase 2
  (in-process executor) complete. Phase 3 (Rust embedding) in progress.

- **PROMPT.md**: Original project prompt for a Go+wazero implementation. The project
  pivoted to Rust+Wasmer when wazero proved insufficient (no threading in standard WASI).
