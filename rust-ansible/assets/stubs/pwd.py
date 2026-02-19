"""Stub pwd (password database) for WASI."""

class struct_passwd:
    def __init__(self, pw_name, pw_passwd, pw_uid, pw_gid, pw_gecos, pw_dir, pw_shell):
        self.pw_name = pw_name
        self.pw_passwd = pw_passwd
        self.pw_uid = pw_uid
        self.pw_gid = pw_gid
        self.pw_gecos = pw_gecos
        self.pw_dir = pw_dir
        self.pw_shell = pw_shell

    def __iter__(self):
        return iter([self.pw_name, self.pw_passwd, self.pw_uid, self.pw_gid,
                     self.pw_gecos, self.pw_dir, self.pw_shell])

def getpwnam(name):
    return struct_passwd('wasi', 'x', 1000, 1000, 'WASI User', '/workspace', '/bin/sh')

def getpwuid(uid):
    return struct_passwd('wasi', 'x', uid, 1000, 'WASI User', '/workspace', '/bin/sh')

def getpwall():
    return [getpwuid(1000)]
