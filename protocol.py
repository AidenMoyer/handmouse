"""Shared wire protocol between the WSL tracker and the Windows mouse relay.

Frame format (little-endian):
    4 bytes  : uint32 message length (N)
    N bytes  : JSON payload (UTF-8)

Messages (type field):
    {"type":"move","x":..,"y":..}        absolute cursor position (screen px)
    {"type":"click","button":"left"}     press+release
    {"type":"down","button":"left"}      button down
    {"type":"up","button":"left"}        button up
    {"type":"scroll","dy":..}            vertical scroll delta (lines)
    {"type":"hscroll","dx":..}           horizontal scroll delta (lines)
    {"type":"ping"}                      keepalive / ready
    {"type":"pong"}                      ack
    {"type":"quit"}                      graceful stop
    {"type":"ok"} / {"type":"error","msg":..}
"""

import json
import struct
import socket

HEADER = struct.Struct("<I")  # uint32 little-endian


class ProtocolError(Exception):
    pass


def encode(msg: dict) -> bytes:
    body = json.dumps(msg).encode("utf-8")
    return HEADER.pack(len(body)) + body


def recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ProtocolError("connection closed")
        buf += chunk
    return buf


def send_msg(sock: socket.socket, msg: dict) -> None:
    sock.sendall(encode(msg))


def recv_msg(sock: socket.socket) -> dict:
    (length,) = HEADER.unpack(recv_exact(sock, HEADER.size))
    if length > 8 * 1024 * 1024:  # 8 MiB sanity cap
        raise ProtocolError("message too large")
    body = recv_exact(sock, length)
    return json.loads(body.decode("utf-8"))
