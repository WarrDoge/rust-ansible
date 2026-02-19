#!/usr/bin/env python3
"""
Test WorkerProcess directly to see if _detach patch works.
"""
import sys
import os

print("=== Direct WorkerProcess Test ===", flush=True)

# Initialize
import wasi_bootstrap
wasi_bootstrap.initialize()
wasi_bootstrap.apply_ansible_patches()

# Verify patches
from ansible.executor.process.worker import WorkerProcess
print(f"WorkerProcess._detach: {WorkerProcess._detach}", flush=True)

# Test calling _detach directly
class FakeWorker:
    pass

print("\nCalling _detach on fake worker...", flush=True)
try:
    WorkerProcess._detach(FakeWorker())
    print("_detach completed successfully", flush=True)
except Exception as e:
    print(f"_detach error: {e}", flush=True)

# Now test full worker
print("\nSetting up minimal worker test...", flush=True)

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

# Create a simple task
play_source = dict(
    name="Test Play",
    hosts='localhost',
    connection='wasi_local',
    gather_facts='no',
    tasks=[dict(action=dict(module='ping'), name='Test ping')]
)
play = Play.load(play_source, variable_manager=variable_manager, loader=loader)
play_context = PlayContext(play=play)

# Get localhost host
hosts = inventory.get_hosts('localhost')
print(f"Hosts: {hosts}", flush=True)

if hosts:
    host = hosts[0]
    task = play.get_tasks()[0][0]
    print(f"Task: {task}", flush=True)
    print(f"Host: {host}", flush=True)

    # Create shared loader
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

    # Create a minimal FinalQueue
    import queue
    class MinimalFinalQueue:
        def __init__(self):
            self._q = queue.Queue()

        def send_display(self, method, *args, **kwargs):
            print(f"  [DISPLAY] {method}: {args}", flush=True)

        def send_task_result(self, result):
            print(f"  [RESULT] {result.return_data}", flush=True)
            self._q.put(result)

        def get(self, *args, **kwargs):
            return self._q.get(*args, **kwargs)

        def put(self, item):
            self._q.put(item)

    final_q = MinimalFinalQueue()

    # Now create and run a WorkerProcess
    print("\nCreating WorkerProcess...", flush=True)
    from ansible.utils.context_objects import CLIArgs

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

    print("WorkerProcess created", flush=True)
    print("Calling worker.start()...", flush=True)

    try:
        worker.start()
        print("worker.start() completed", flush=True)
    except Exception as e:
        print(f"worker.start() error: {e}", flush=True)
        import traceback
        traceback.print_exc()

print("\n=== Done ===", flush=True)
