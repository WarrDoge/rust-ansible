#!/usr/bin/env python3
"""
Trace to find where fcntl.lockf error occurs.
"""
import sys
import traceback

print("=== Trace Error Test ===")

# Patch fcntl.lockf immediately to trace all calls
import fcntl as _fcntl
_original_lockf = _fcntl.lockf

def tracing_lockf(*args, **kwargs):
    print('\n=== fcntl.lockf CALLED ===', file=sys.__stdout__, flush=True)
    traceback.print_stack(file=sys.__stdout__)
    print(f'args: {args}', file=sys.__stdout__, flush=True)
    print('========================\n', file=sys.__stdout__, flush=True)
    return _original_lockf(*args, **kwargs)

_fcntl.lockf = tracing_lockf
print("1. Installed fcntl.lockf tracer")

# Now standard bootstrap
import wasi_bootstrap
wasi_bootstrap.apply_ansible_patches()
print("2. Applied wasi_bootstrap patches")

# Check fcntl.lockf is still our tracer (wasi_bootstrap might overwrite it)
print(f"3. fcntl.lockf is now: {_fcntl.lockf}")

# Verify the stub is in place
import fcntl
print(f"4. Re-imported fcntl.lockf: {fcntl.lockf}")
print(f"5. Same module? {_fcntl is fcntl}")

# Restore our tracer if wasi_bootstrap overwrote it
if _fcntl.lockf != tracing_lockf:
    print("   -> Restoring tracer...")
    _fcntl.lockf = tracing_lockf

# Also patch the stub to trace calls to it
from wasi_bootstrap import patch_fcntl_module
print(f"6. patch_fcntl_module._original_lockf: {patch_fcntl_module.__code__.co_consts if hasattr(patch_fcntl_module, '__code__') else 'N/A'}")

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

print("7. Imports done")

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

# Monkey-patch ActionBase._execute_module to see what's happening
from ansible.plugins.action import ActionBase
_original_execute_module = ActionBase._execute_module

def traced_execute_module(self, *args, **kwargs):
    print('\n>>> ActionBase._execute_module CALLED', file=sys.__stdout__, flush=True)
    print(f'    module_name={getattr(self, "_task", None) and self._task.action}', file=sys.__stdout__, flush=True)
    try:
        result = _original_execute_module(self, *args, **kwargs)
        print(f'<<< _execute_module returned: {result}', file=sys.__stdout__, flush=True)
        return result
    except Exception as e:
        print(f'<<< _execute_module EXCEPTION: {e}', file=sys.__stdout__, flush=True)
        traceback.print_exc(file=sys.__stdout__)
        raise

ActionBase._execute_module = traced_execute_module

# Also trace _low_level_execute_command
_original_low_level = ActionBase._low_level_execute_command

def traced_low_level(self, *args, **kwargs):
    print('\n>>> ActionBase._low_level_execute_command CALLED', file=sys.__stdout__, flush=True)
    try:
        result = _original_low_level(self, *args, **kwargs)
        print(f'<<< _low_level_execute_command returned: rc={result[0]}', file=sys.__stdout__, flush=True)
        return result
    except Exception as e:
        print(f'<<< _low_level_execute_command EXCEPTION: {e}', file=sys.__stdout__, flush=True)
        traceback.print_exc(file=sys.__stdout__)
        raise

ActionBase._low_level_execute_command = traced_low_level

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

print('8. Running executor...')
try:
    result = executor.run()
    print(f'\n9. Result: {result}')
except Exception as e:
    print(f'\n9. Exception: {e}')
    traceback.print_exc()

print("\n=== Test Complete ===")
