"""Stub grp (group database) for WASI."""

class struct_group:
    def __init__(self, gr_name, gr_passwd, gr_gid, gr_mem):
        self.gr_name = gr_name
        self.gr_passwd = gr_passwd
        self.gr_gid = gr_gid
        self.gr_mem = gr_mem

    def __iter__(self):
        return iter([self.gr_name, self.gr_passwd, self.gr_gid, self.gr_mem])

def getgrnam(name):
    return struct_group('wasi', 'x', 1000, ['wasi'])

def getgrgid(gid):
    return struct_group('wasi', 'x', gid, ['wasi'])

def getgrall():
    return [getgrgid(1000)]
