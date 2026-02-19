#!/usr/bin/env python3
"""
Minimal test - just run ansible ping directly.
"""
import sys
import os

print("=== Minimal Test ===", flush=True)

# Initialize
import wasi_bootstrap
wasi_bootstrap.initialize()

# Apply patches before importing ansible.executor.process.worker
wasi_bootstrap.apply_ansible_patches()

# Verify patches
from ansible.executor.process.worker import WorkerProcess
print(f"WorkerProcess._detach: {WorkerProcess._detach}", flush=True)

# Check if _detach is our noop
import types
print(f"_detach code: {WorkerProcess._detach.__code__.co_code}", flush=True)

# Run a simple test
from ansible import context
from ansible.module_utils.common.collections import ImmutableDict
from ansible.cli.adhoc import AdHocCLI

context._init_global_context(ImmutableDict(
    connection='wasi_local',
    module_path=['/site-packages/ansible/modules'],
    forks=1,
    become=None,
    become_method=None,
    become_user=None,
    check=False,
    diff=False,
    verbosity=4,
    syntax=False,
    start_at_task=None,
    remote_user='wasi',
    module_name='ping',
    args='',
    one_line=True,
    tree=None,
    ask_vault_pass=False,
    vault_password_files=[],
    poll=0,
    seconds=0,
    basedir=None,
    listhosts=None,
    subset=None,
    extra_vars=[],
    private_key_file=None,
    ask_pass=False,
))

print("\nRunning ad-hoc ping...", flush=True)
try:
    cli = AdHocCLI(['ansible', 'localhost', '-m', 'ping', '-c', 'wasi_local'])
    cli.parse()
    result = cli.run()
    print(f"Result: {result}", flush=True)
except Exception as e:
    print(f"Error: {e}", flush=True)
    import traceback
    traceback.print_exc()

print("\n=== Done ===", flush=True)
