"""Stub grp (group database) for WASI."""

import os


class struct_group:
    def __init__(self, gr_name, gr_passwd, gr_gid, gr_mem):
        self.gr_name = gr_name
        self.gr_passwd = gr_passwd
        self.gr_gid = gr_gid
        self.gr_mem = gr_mem

    def __iter__(self):
        return iter([self.gr_name, self.gr_passwd, self.gr_gid, self.gr_mem])


def _default_user():
    return os.environ.get('USER', 'wasi')


def getgrnam(name):
    return struct_group(name, 'x', 1000, [name])


def getgrgid(gid):
    user = _default_user()
    return struct_group(user, 'x', gid, [user])


def getgrall():
    return [getgrgid(1000)]
