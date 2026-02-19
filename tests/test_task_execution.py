#!/usr/bin/env python3
"""
Test task execution specifically to find where it hangs.
"""
import sys
import os

print("=== Task Execution Trace ===", flush=True)

# Initialize
import wasi_bootstrap
wasi_bootstrap.initialize()

print("1. Setting up context...", flush=True)

# IMPORTANT: Import WorkerProcess FIRST and patch it before other imports
# This ensures the patch is in place before any other code caches the class
from ansible.executor.process.worker import WorkerProcess
print(f"   Before patch - WorkerProcess._detach: {WorkerProcess._detach}", flush=True)

# Apply ansible patches
wasi_bootstrap.apply_ansible_patches()
print(f"   After patch - WorkerProcess._detach: {WorkerProcess._detach}", flush=True)

# Now import other ansible modules
from ansible.parsing.dataloader import DataLoader
from ansible.inventory.manager import InventoryManager
from ansible.vars.manager import VariableManager
from ansible.playbook.play_context import PlayContext
from ansible.playbook.play import Play
from ansible.executor.task_queue_manager import TaskQueueManager
from ansible.plugins.loader import connection_loader
from ansible import context
from ansible.module_utils.common.collections import ImmutableDict

# Verify patch is still in place after other imports
print(f"   After imports - WorkerProcess._detach: {WorkerProcess._detach}", flush=True)

# Set context
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
))

print("2. Loading inventory...")
loader = DataLoader()
inventory = InventoryManager(loader=loader, sources=['localhost,'])
variable_manager = VariableManager(loader=loader, inventory=inventory)

print("3. Creating play...")
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

print("4. Creating TaskQueueManager...")
# TQM manages the workers
tqm = None
try:
    tqm = TaskQueueManager(
        inventory=inventory,
        variable_manager=variable_manager,
        loader=loader,
        passwords={},
    )
    print(f"   TQM created: {tqm}")
    print(f"   TQM forks: {tqm._forks}")

    print("5. Running play...")
    print("   This is where it might hang...")

    # Try to run
    result = tqm.run(play)
    print(f"   Play result: {result}")

except Exception as e:
    print(f"   Error: {e}")
    import traceback
    traceback.print_exc()

finally:
    if tqm:
        print("6. Cleaning up TQM...")
        tqm.cleanup()

print("\n=== Test Complete ===")
