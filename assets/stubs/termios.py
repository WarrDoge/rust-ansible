"""Stub termios for WASI."""

# Terminal control constants
TCSAFLUSH = 2
TCSADRAIN = 1
TCSANOW = 0
TIOCGWINSZ = 0x5413

# Input flags
BRKINT = 0x0002
ICRNL = 0x0100
INPCK = 0x0010
ISTRIP = 0x0020
IXON = 0x0400

# Output flags
OPOST = 0x0001

# Control flags
CSIZE = 0x0030
PARENB = 0x0100
CS8 = 0x0030

# Local flags
ECHO = 0x0008
ICANON = 0x0002
IEXTEN = 0x8000
ISIG = 0x0001

# cc indices
VMIN = 6
VTIME = 5

def tcgetattr(fd):
    # Return a default mode list: [iflag, oflag, cflag, lflag, ispeed, ospeed, cc]
    return [0, 0, 0, 0, 0, 0, [0] * 32]

def tcsetattr(fd, when, attributes):
    pass

def tcsendbreak(fd, duration):
    pass

def tcdrain(fd):
    pass

def tcflush(fd, queue):
    pass

def tcflow(fd, action):
    pass
