#!/usr/bin/env python3
"""
Test executing a real Ansible module through the action system.
This will use the AnsiballZ wrapper.
"""
import sys
import os

print("=== Action/Module Test ===", flush=True)

# Initialize
import wasi_bootstrap
wasi_bootstrap.initialize()
wasi_bootstrap.apply_ansible_patches()

from ansible.parsing.dataloader import DataLoader
from ansible.inventory.manager import InventoryManager
from ansible.vars.manager import VariableManager
from ansible.playbook.play import Play
from ansible.playbook.task import Task
from ansible.playbook.play_context import PlayContext
from ansible.executor.task_executor import TaskExecutor
from ansible.plugins import loader as plugin_loader
from ansible import context
from ansible.module_utils.common.collections import ImmutableDict
from ansible.utils.display import Display
import types

display = Display()

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

print("1. Loading inventory...", flush=True)
loader = DataLoader()
inventory = InventoryManager(loader=loader, sources=['localhost,'])
variable_manager = VariableManager(loader=loader, inventory=inventory)

print("2. Creating play with ping task...", flush=True)
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

# Create shared loaders
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

# Create a minimal final queue
import queue
class MinimalFinalQueue:
    def __init__(self):
        self._q = queue.Queue()

    def send_display(self, method, *args, **kwargs):
        pass  # Ignore display messages

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

print("4. Executing task (this will use AnsiballZ wrapper)...", flush=True)
try:
    result = executor.run()
    print(f"\n   Task result type: {type(result)}", flush=True)
    print(f"   Result: {result}", flush=True)

    if isinstance(result, dict):
        if result.get('ping') == 'pong':
            print("\n   SUCCESS: Ping module worked!", flush=True)
        else:
            print(f"\n   UNEXPECTED: {result}", flush=True)
            if 'msg' in result:
                print(f"   Message: {result['msg']}", flush=True)
            if 'exception' in result:
                print(f"   Exception:\n{result['exception']}", flush=True)

except Exception as e:
    print(f"\n   ERROR: {e}", flush=True)
    import traceback
    traceback.print_exc()

print("\n=== Test Complete ===")
