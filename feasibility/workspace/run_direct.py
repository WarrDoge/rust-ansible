"""Run ansible playbook directly without CLI wrapper."""
import sys
import os
import atexit

def at_exit():
    print("atexit handler called", file=sys.stderr, flush=True)
atexit.register(at_exit)

print("Starting direct ansible test...", file=sys.stderr, flush=True)

exec(open('/workspace/bootstrap.py').read())
print("Bootstrap loaded", file=sys.stderr, flush=True)

os.chdir('/workspace')
print("Working dir:", os.getcwd(), file=sys.stderr, flush=True)

# Apply strategy patch
apply_strategy_patch()
print("Strategy patch applied", file=sys.stderr, flush=True)

# Import ansible components directly
print("Importing ansible components...", file=sys.stderr, flush=True)
from ansible.parsing.dataloader import DataLoader
from ansible.inventory.manager import InventoryManager
from ansible.vars.manager import VariableManager
from ansible.executor.playbook_executor import PlaybookExecutor
from ansible import context
from ansible.plugins.loader import init_plugin_loader
from argparse import Namespace

print("All imports successful", file=sys.stderr, flush=True)

# Set up context - need all required fields as namespace
cli_args = Namespace(
    args=['test.yml'],
    connection='local',
    forks=1,
    become=False,
    become_method=None,
    become_user=None,
    check=False,
    diff=False,
    verbosity=3,
    syntax=False,
    start_at_task=None,
    listhosts=False,
    listtasks=False,
    listtags=False,
    step=False,
    collections_path=[],
    module_path=[],
    subset=None,
    extra_vars=[],
    inventory=['inventory'],
    flush_cache=False,
    force_handlers=False,
    private_key_file=None,
    remote_user=None,
    timeout=10,
    ssh_common_args=None,
    ssh_extra_args=None,
    sftp_extra_args=None,
    scp_extra_args=None,
    tags=[],
    skip_tags=[],
    vault_ids=[],
    vault_password_files=[],
    ask_vault_pass=False,
)
context._init_global_context(cli_args)
print("Context initialized, syntax key:", context.CLIARGS.get('syntax'), file=sys.stderr, flush=True)

# Initialize plugin loader - THIS IS CRITICAL for collection support
print("Initializing plugin loader...", file=sys.stderr, flush=True)
init_plugin_loader([])
print("Plugin loader initialized", file=sys.stderr, flush=True)

# Create loader
loader = DataLoader()
print("Loader created", file=sys.stderr, flush=True)

# Create inventory
inventory = InventoryManager(loader=loader, sources=['inventory'])
print("Inventory created:", list(inventory.hosts.keys()), file=sys.stderr, flush=True)

# Create variable manager
variable_manager = VariableManager(loader=loader, inventory=inventory)
print("Variable manager created", file=sys.stderr, flush=True)

# Create playbook executor
print("Creating PlaybookExecutor...", file=sys.stderr, flush=True)
pbex = PlaybookExecutor(
    playbooks=['test.yml'],
    inventory=inventory,
    variable_manager=variable_manager,
    loader=loader,
    passwords={}
)
print("PlaybookExecutor created", file=sys.stderr, flush=True)

# Run
print("Running playbook...", file=sys.stderr, flush=True)
try:
    result = pbex.run()
    print("Playbook result:", result, file=sys.stderr, flush=True)
except Exception as e:
    print("Error:", type(e).__name__, e, file=sys.stderr, flush=True)
    import traceback
    traceback.print_exc()
