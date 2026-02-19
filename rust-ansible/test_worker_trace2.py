#!/usr/bin/env python3
"""
Detailed tracing of worker execution.
"""
import sys
import os

print("=== Detailed Worker Trace ===", flush=True)

# Initialize
import wasi_bootstrap
wasi_bootstrap.initialize()

# Patch WorkerProcess.run to add tracing
from ansible.executor.process import worker as worker_module

_original_run = worker_module.WorkerProcess.run

def traced_run(self):
    print("  [TRACE] run() entered", flush=True)
    from ansible.utils.display import Display
    display = Display()

    print("  [TRACE] calling display.set_queue", flush=True)
    display.set_queue(self._final_q)
    print("  [TRACE] display.set_queue done", flush=True)

    print("  [TRACE] calling _detach", flush=True)
    self._detach()
    print("  [TRACE] _detach done", flush=True)

    import signal
    print("  [TRACE] setting signal handlers", flush=True)
    signal.signal(signal.SIGINT, self._term)
    signal.signal(signal.SIGTERM, self._term)
    print("  [TRACE] signal handlers set", flush=True)

    print("  [TRACE] entering TaskContext", flush=True)
    from ansible._internal import _task
    try:
        with _task.TaskContext(self._task):
            print("  [TRACE] inside TaskContext, calling _run", flush=True)
            result = self._run()
            print(f"  [TRACE] _run returned: {result}", flush=True)
            return result
    except BaseException as e:
        print(f"  [TRACE] exception in run: {e}", flush=True)
        import traceback as tb
        tb.print_exc()
        self._hard_exit(tb.format_exc())

worker_module.WorkerProcess.run = traced_run

# Also trace _run
_original_inner_run = worker_module.WorkerProcess._run

def traced_inner_run(self):
    print("  [TRACE] _run() entered", flush=True)

    global current_worker
    worker_module.current_worker = self

    print("  [TRACE] creating TaskExecutor", flush=True)
    from ansible.executor.task_executor import TaskExecutor
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
    print("  [TRACE] TaskExecutor created", flush=True)

    print("  [TRACE] calling executor.run()", flush=True)
    try:
        executor_result = executor.run()
        print(f"  [TRACE] executor.run() returned: {type(executor_result)}", flush=True)
    except Exception as e:
        print(f"  [TRACE] executor.run() exception: {e}", flush=True)
        raise

    print("  [TRACE] cleaning up host vars", flush=True)
    self._host.vars = dict()
    self._host.groups = []

    print("  [TRACE] sending result", flush=True)
    from ansible.executor.task_result import _RawTaskResult
    try:
        self._final_q.send_task_result(_RawTaskResult(
            host=self._host,
            task=self._task,
            return_data=executor_result,
            task_fields=self._task.dump_attrs(),
        ))
        print("  [TRACE] result sent", flush=True)
    except Exception as e:
        print(f"  [TRACE] send_task_result exception: {e}", flush=True)
        raise

worker_module.WorkerProcess._run = traced_inner_run

# Apply other patches
wasi_bootstrap.apply_ansible_patches()

# Now run the test
from ansible.parsing.dataloader import DataLoader
from ansible.inventory.manager import InventoryManager
from ansible.inventory.host import Host
from ansible.vars.manager import VariableManager
from ansible.playbook.play import Play
from ansible.playbook.task import Task
from ansible.playbook.play_context import PlayContext
from ansible.executor.task_queue_manager import TaskQueueManager
from ansible.plugins import loader as plugin_loader
from ansible import context
from ansible.module_utils.common.collections import ImmutableDict
import types

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

loader = DataLoader()
inventory = InventoryManager(loader=loader, sources=['localhost,'])
variable_manager = VariableManager(loader=loader, inventory=inventory)

play_source = dict(
    name="Test Play",
    hosts='localhost',
    connection='wasi_local',
    gather_facts='no',
    tasks=[dict(action=dict(module='ping'), name='Test ping')]
)
play = Play.load(play_source, variable_manager=variable_manager, loader=loader)
play_context = PlayContext(play=play)

hosts = inventory.get_hosts('localhost')
host = hosts[0]
task = play.get_tasks()[0][0]

shared_loader = types.SimpleNamespace(
    action=plugin_loader.action_loader,
    become=plugin_loader.become_loader,
    cache=plugin_loader.cache_loader,
    callback=plugin_loader.callback_loader,
    connection=plugin_loader.connection_loader,
    httpapi=plugin_loader.httpapi_loader,
    lookup=plugin_loader.lookup_loader,
    shell=plugin_loader.shell_loader,
    module=plugin_loader.module_loader,
    strategy=plugin_loader.strategy_loader,
    terminal=plugin_loader.terminal_loader,
    test=plugin_loader.test_loader,
    filter=plugin_loader.filter_loader,
    netconf=plugin_loader.netconf_loader,
)

import queue
class MinimalFinalQueue:
    def __init__(self):
        self._q = queue.Queue()

    def send_display(self, method, *args, **kwargs):
        print(f"  [DISPLAY] {method}: {args}", flush=True)

    def send_task_result(self, result):
        print(f"  [RESULT] type={type(result)}", flush=True)
        self._q.put(result)

    def get(self, *args, **kwargs):
        return self._q.get(*args, **kwargs)

    def put(self, item):
        self._q.put(item)

final_q = MinimalFinalQueue()

print("\nCreating and starting WorkerProcess...", flush=True)
from ansible.executor.process.worker import WorkerProcess

worker = WorkerProcess(
    final_q=final_q,
    task_vars=variable_manager.get_vars(host=host),
    host=host,
    task=task,
    play_context=play_context,
    loader=loader,
    variable_manager=variable_manager,
    shared_loader_obj=shared_loader,
    worker_id=0,
    cliargs=context.CLIARGS,
)

print("Calling worker.start()...", flush=True)
try:
    worker.start()
    print("worker.start() completed", flush=True)
except Exception as e:
    print(f"worker.start() error: {e}", flush=True)
    import traceback
    traceback.print_exc()

print("\n=== Done ===", flush=True)
