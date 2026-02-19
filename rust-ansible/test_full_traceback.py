#!/usr/bin/env python3
"""
Get full traceback of the fcntl.lockf error.
"""
import sys
import os

print("=== Full Traceback Test ===", flush=True)

# Initialize
import wasi_bootstrap
wasi_bootstrap.initialize()
wasi_bootstrap.apply_ansible_patches()

from ansible.parsing.dataloader import DataLoader
from ansible.inventory.manager import InventoryManager
from ansible.vars.manager import VariableManager
from ansible.playbook.play import Play
from ansible.playbook.play_context import PlayContext
from ansible.executor.task_executor import TaskExecutor
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

print("1. Loading inventory...", flush=True)
loader = DataLoader()
inventory = InventoryManager(loader=loader, sources=['localhost,'])
variable_manager = VariableManager(loader=loader, inventory=inventory)

print("2. Creating play...", flush=True)
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
    action_loader=plugin_loader.action_loader,
    become_loader=plugin_loader.become_loader,
    cache_loader=plugin_loader.cache_loader,
    callback_loader=plugin_loader.callback_loader,
    connection_loader=plugin_loader.connection_loader,
    httpapi_loader=plugin_loader.httpapi_loader,
    lookup_loader=plugin_loader.lookup_loader,
    shell_loader=plugin_loader.shell_loader,
    module_loader=plugin_loader.module_loader,
    strategy_loader=plugin_loader.strategy_loader,
    terminal_loader=plugin_loader.terminal_loader,
    test_loader=plugin_loader.test_loader,
    filter_loader=plugin_loader.filter_loader,
    netconf_loader=plugin_loader.netconf_loader,
)

import queue
class MinimalFinalQueue:
    def __init__(self):
        self._q = queue.Queue()

    def send_display(self, method, *args, **kwargs):
        pass

    def send_task_result(self, result):
        self._q.put(result)

    def get(self, *args, **kwargs):
        return self._q.get(*args, **kwargs)

    def put(self, item):
        self._q.put(item)

final_q = MinimalFinalQueue()

print("3. Creating TaskExecutor...", flush=True)
executor = TaskExecutor(
    host,
    task,
    variable_manager.get_vars(host=host),
    play_context,
    loader,
    shared_loader,
    final_q,
    variable_manager,
)

print("4. Executing task...", flush=True)
try:
    # Catch ALL exceptions, including those from ansible
    import traceback
    result = executor.run()
    print(f"\n   Result keys: {result.keys()}", flush=True)

    # Try to extract more detail from the exception
    if 'exception' in result:
        exc = result['exception']
        print(f"\n   Exception type: {type(exc)}", flush=True)
        print(f"   Exception: {exc}", flush=True)

        # Try to get the original exception if it's wrapped
        if hasattr(exc, 'event'):
            print(f"\n   Event: {exc.event}", flush=True)
            if hasattr(exc.event, 'chain') and exc.event.chain:
                print(f"   Chain: {exc.event.chain}", flush=True)
                if hasattr(exc.event.chain, 'event'):
                    print(f"   Chained event: {exc.event.chain.event}", flush=True)

except BaseException as e:
    print(f"\n   CAUGHT EXCEPTION: {type(e).__name__}: {e}", flush=True)
    print("\n   Full traceback:", flush=True)
    traceback.print_exc()

print("\n=== Test Complete ===")
