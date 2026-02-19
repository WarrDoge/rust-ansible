#!/usr/bin/env python3
"""
Trace fcntl.lockf calls during task execution.
"""
import fcntl
import traceback
import sys

print("=== FCNTL Trace Test ===\n")

# Get the original stub (which should be the wasi_bootstrap stub)
_original_lockf = fcntl.lockf

def tracing_lockf(*args, **kwargs):
    print('\n=== fcntl.lockf called ===', flush=True)
    traceback.print_stack()
    print(f'args: {args}', flush=True)
    print(f'kwargs: {kwargs}', flush=True)
    print('========================\n', flush=True)
    return _original_lockf(*args, **kwargs)

fcntl.lockf = tracing_lockf

# Now run the actual test
import wasi_bootstrap
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
import queue

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
    name='Test Play',
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

print('Running executor...')
try:
    result = executor.run()
    print(f'\nResult: {result}')
except Exception as e:
    print(f'\nException: {e}')
    traceback.print_exc()

print("\n=== Test Complete ===")
