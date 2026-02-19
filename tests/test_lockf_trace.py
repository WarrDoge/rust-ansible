#!/usr/bin/env python3
"""
Trace where fcntl.lockf is being called.
"""
import sys
import os

print("=== fcntl.lockf Trace ===", flush=True)

# Initialize bootstrap FIRST
import wasi_bootstrap
wasi_bootstrap.initialize()

# Patch fcntl.lockf to print stack trace when called
import fcntl
import traceback

_original_lockf = fcntl.lockf

def traced_lockf(fd, operation, length=0, start=0, whence=0):
    print("\n[LOCKF CALL] fcntl.lockf was called!", flush=True)
    print("Stack trace:", flush=True)
    traceback.print_stack()
    # Call original (which should be our stub now)
    return _original_lockf(fd, operation, length, start, whence)

fcntl.lockf = traced_lockf

# Now do a minimal ansible import and run
print("\nImporting ansible...", flush=True)
from ansible.parsing.dataloader import DataLoader
from ansible.inventory.manager import InventoryManager
from ansible.vars.manager import VariableManager
from ansible.playbook.play import Play
from ansible.executor.task_queue_manager import TaskQueueManager
from ansible import context
from ansible.module_utils.common.collections import ImmutableDict

# Apply ansible patches
wasi_bootstrap.apply_ansible_patches()

context._init_global_context(ImmutableDict(
    connection='wasi_local',
    module_path=['/site-packages/ansible/modules'],
    forks=1,
    become=None,
    become_method=None,
    become_user=None,
    check=False,
    diff=False,
    verbosity=0,
    syntax=False,
    start_at_task=None,
    remote_user='wasi',
))

print("\nRunning task...", flush=True)
loader = DataLoader()
inventory = InventoryManager(loader=loader, sources=['localhost,'])
variable_manager = VariableManager(loader=loader, inventory=inventory)

play_source = dict(
    name="Test Play",
    hosts='localhost',
    connection='wasi_local',
    gather_facts='no',
    tasks=[
        dict(action=dict(module='ping'), name='Test ping'),
    ]
)
play = Play.load(play_source, variable_manager=variable_manager, loader=loader)

tqm = None
try:
    tqm = TaskQueueManager(
        inventory=inventory,
        variable_manager=variable_manager,
        loader=loader,
        passwords={},
    )
    result = tqm.run(play)
    print(f"\nPlay result: {result}", flush=True)
except Exception as e:
    print(f"\nError: {e}", flush=True)
    traceback.print_exc()
finally:
    if tqm:
        tqm.cleanup()

print("\n=== Trace Complete ===", flush=True)
