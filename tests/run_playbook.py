#!/usr/bin/env python3
"""
Run ansible-playbook with WASI patches applied.
"""
import sys

# Initialize WASI bootstrap
import wasi_bootstrap
wasi_bootstrap.initialize()

# Import WorkerProcess and apply patches BEFORE any other ansible imports
from ansible.executor.process.worker import WorkerProcess
wasi_bootstrap.apply_ansible_patches()

# Now run the playbook CLI
from ansible.cli.playbook import PlaybookCLI

# Pass through command line args (skip this script name)
args = ['ansible-playbook'] + sys.argv[1:]
cli = PlaybookCLI(args)
sys.exit(cli.run())
