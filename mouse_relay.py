# mouse_relay.py - part 1/3
"""Windows-side mouse relay. Listens on TCP and drives the real Windows
mouse/scroll via pyautogui. Run this on Windows (PowerShell):

    python mouse_relay.py
"""
import argparse
import socket
import pyautogui

pyautogui.FAILSAFE = False

import protocol  # noqa: E402  (same directory)


def do_action(msg):
    t = msg.get("type")
    if t == "move":
        pyautogui.moveTo(msg["x"], msg["y"], _pause=False)
    elif t == "click":
        pyautogui.click(button=msg.get("button", "left"), _pause=False)
    elif t == "down":
        pyautogui.mouseDown(button=msg.get("button", "left"), _pause=False)
    elif t == "up":
        pyautogui.mouseUp(button=msg.get("button", "left"), _pause=False)
    elif t == "scroll":
        dy = int(msg.get("dy", 0))
        dx = int(msg.get("dx", 0))
        if dy:
            pyautogui.scroll(dy, _pause=False)
        if dx:
            pyautogui.hscroll(dx, _pause=False)
    elif t == "ping":
        protocol.send_msg(_CLIENT, {"type": "pong"})
    elif t == "quit":
        return False
    elif t == "error":
        print("client error:", msg)
    return True
# mouse_relay.py - part 2/3
_CLIENT = None


def serve(host, port, once=False):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(1)
    print(f"mouse_relay listening on {host}:{port} — waiting for WSL tracker")
    global _CLIENT
    while True:
        client, addr = server.accept()
        print("tracker connected from", addr)
        _CLIENT = client
        try:
            while True:
                msg = protocol.recv_msg(client)
                if not do_action(msg):
                    break
        except (protocol.ProtocolError, ConnectionError):
            pass
        finally:
            _CLIENT = None
            client.close()
        if once:
            break
    server.close()
# mouse_relay.py - part 3/3
def main():
    ap = argparse.ArgumentParser(description="Windows mouse relay for handmouse")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=48711)
    ap.add_argument("--once", action="store_true", help="serve one client then exit")
    args = ap.parse_args()
    try:
        serve(args.host, args.port, once=args.once)
    except KeyboardInterrupt:
        print("\nrelay stopped")


if __name__ == "__main__":
    main()
