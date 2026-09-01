# test_protocol.py - part 1/2 (single logical unit, small)
import socket
import threading
import protocol


def test_roundtrip():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    def client():
        s = socket.create_connection(("127.0.0.1", port))
        protocol.send_msg(s, {"type": "move", "x": 10, "y": 20})
        got = protocol.recv_msg(s)
        assert got == {"type": "pong"}, got
        protocol.send_msg(s, {"type": "quit"})
        s.close()

    def srv():
        c, _ = server.accept()
        m = protocol.recv_msg(c)
        assert m == {"type": "move", "x": 10, "y": 20}, m
        protocol.send_msg(c, {"type": "pong"})
        m2 = protocol.recv_msg(c)
        assert m2["type"] == "quit"
        c.close()

    t = threading.Thread(target=client)
    srv_t = threading.Thread(target=srv)
    t.start(); srv_t.start()
    t.join(); srv_t.join(); server.close()
    print("OK: protocol roundtrip")
# test_protocol.py - part 2/2 (single logical unit, small)
if __name__ == "__main__":
    test_roundtrip()
