"""Run ansible playbook in WASI."""
import sys
import os
import atexit

def at_exit():
    print("atexit handler called", file=sys.stderr, flush=True)
atexit.register(at_exit)

print("Starting WASI ansible test...", file=sys.stderr, flush=True)

exec(open('/workspace/bootstrap.py').read())
print("Bootstrap loaded", file=sys.stderr, flush=True)

os.chdir('/workspace')
print("Working dir:", os.getcwd(), file=sys.stderr, flush=True)

from ansible.cli.playbook import PlaybookCLI
print("PlaybookCLI imported", file=sys.stderr, flush=True)

# Apply strategy patch after ansible is loaded
apply_strategy_patch()
print("Strategy patch applied", file=sys.stderr, flush=True)

sys.argv = ['ansible-playbook', '-i', 'inventory', 'test.yml', '-vvv']
print("Running:", sys.argv, file=sys.stderr, flush=True)

cli = PlaybookCLI(sys.argv)
print("CLI created", file=sys.stderr, flush=True)

cli.parse()
print("CLI parsed", file=sys.stderr, flush=True)

print("Calling cli.run()...", file=sys.stderr, flush=True)
result = cli.run()
print("cli.run() returned:", result, file=sys.stderr, flush=True)
