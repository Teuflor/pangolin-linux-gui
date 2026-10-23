"""Local network information without external tools."""
from __future__ import annotations

import fcntl
import socket
import struct

DEFAULT_INTERFACE = "pangolin"  # `pangolin up client --interface-name` default
_SIOCGIFADDR = 0x8915


def interface_ipv4(name: str = DEFAULT_INTERFACE) -> str:
    """IPv4 address of a network interface, or "" if it does not exist / has none."""
    if not name or len(name) > 15:
        return ""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        packed = fcntl.ioctl(sock.fileno(), _SIOCGIFADDR, struct.pack("256s", name.encode()))
        return socket.inet_ntoa(packed[20:24])
    except OSError:
        return ""
    finally:
        sock.close()
