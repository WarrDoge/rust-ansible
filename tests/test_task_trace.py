#!/usr/bin/env python3
"""
Deep trace of task execution to find the exact hang location.
"""
import sys
import os

print("=== Task Execution Deep Trace ===", flush=True)

# Initialize
import wasi_bootstrap
wasi_bootstrap.initialize()

# Patch WorkerProcess.run to add tracing
from ansible.executor.process.worker import WorkerProcess

_original_run = WorkerProcess.run
_original_inner_run = WorkerProcess._run

def traced_run(self):
    print(f"  [TRACE] WorkerProcess.run() started", flush=True)
    try:
        from ansible.utils.display import Display
        display = Display()
        print(f"  [TRACE] Calling display.set_queue", flush=True)
        display.set_queue(self._final_q)
        print(f"  [TRACE] display.set_queue completed", flush=True)

        print(f"  [TRACE] Calling _detach (noop)", flush=True)
        self._detach()
        print(f"  [TRACE] _detach completed", flush=True)

        import signal
        print(f"  [TRACE] Setting up signal handlers", flush=True)
        signal.signal(signal.SIGINT, self._term)
        signal.signal(signal.SIGTERM, self._term)
        print(f"  [TRACE] Signal handlers set", flush=True)

        print(f"  [TRACE] Calling _run()", flush=True)
        return self._run()
    except Exception as e:
        print(f"  [TRACE] WorkerProcess.run() exception: {e}", flush=True)
        import traceback
        traceback.print_exc()
        raise

def traced_inner_run(self):
    print(f"  [TRACE] WorkerProcess._run() started", flush=True)
    try:
        from ansible.executor.task_executor import TaskExecutor
        print(f"  [TRACE] Creating TaskExecutor", flush=True)

        executor = TaskExecutor(
            self._host,
            self._task,
            self._task_vars,
            self._play_context,
            self._loader,
            self._shared_loader_obj,
            self._final_q,
            self._variable_manager,
        )
        print(f"  [TRACE] TaskExecutor created, calling run()", flush=True)

        executor_result = executor.run()
        print(f"  [TRACE] TaskExecutor.run() completed: {executor_result}", flush=True)

        # Send result
        from ansible.executor.task_result import _RawTaskResult
        print(f"  [TRACE] Sending task result", flush=True)
        self._final_q.send_task_result(_RawTaskResult(
            host=self._host,
            task=self._task,
            return_data=executor_result,
            task_fields=self._task.dump_attrs(),
        ))
        print(f"  [TRACE] Task result sent", flush=True)

    except Exception as e:
        print(f"  [TRACE] WorkerProcess._run() exception: {e}", flush=True)
        import traceback
        traceback.print_exc()
        raise

WorkerProcess.run = traced_run
WorkerProcess._run = traced_inner_run

# Apply other patches
wasi_bootstrap.apply_ansible_patches()

print("1. Setting up context...", flush=True)
from ansible.parsing.dataloader import DataLoader
from ansible.inventory.manager import InventoryManager
from ansible.vars.manager import VariableManager
from ansible.playbook.play import Play
from ansible.executor.task_queue_manager import TaskQueueManager
from ansible import context
from ansible.module_utils.common.collections import ImmutableDict

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

print("2. Loading inventory...", flush=True)
loader = DataLoader()
inventory = InventoryManager(loader=loader, sources=['localhost,'])
variable_manager = VariableManager(loader=loader, inventory=inventory)

print("3. Creating play...", flush=True)
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

print("4. Creating TaskQueueManager...", flush=True)
tqm = None
try:
    tqm = TaskQueueManager(
        inventory=inventory,
        variable_manager=variable_manager,
        loader=loader,
        passwords={},
    )

    print("5. Running play...", flush=True)
    result = tqm.run(play)
    print(f"6. Play result: {result}", flush=True)

except Exception as e:
    print(f"Error: {e}", flush=True)
    import traceback
    traceback.print_exc()

finally:
    if tqm:
        print("7. Cleaning up TQM...", flush=True)
        tqm.cleanup()

print("\n=== Test Complete ===", flush=True)
