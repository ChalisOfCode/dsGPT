"""Small bounded localhost-only CDP client; no downloaded browser or global settings."""

import base64
import hashlib
import json
import os
import socket
import struct
import time
from urllib.parse import urlsplit


class CDP:
    def __init__(self, url):
        parsed = urlsplit(url)
        if parsed.scheme != "ws" or parsed.hostname != "127.0.0.1":
            raise ValueError("CDP must stay on the owned loopback port")
        self.sock = socket.create_connection((parsed.hostname, parsed.port), timeout=20)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(
            (
                f"GET {parsed.path} HTTP/1.1\r\nHost: 127.0.0.1:{parsed.port}\r\n"
                "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
            ).encode()
        )
        headers = bytearray()
        while not headers.endswith(b"\r\n\r\n"):
            headers.extend(self.read(1))
            if len(headers) > 16384:
                raise ValueError("Oversized CDP handshake")
        expected = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
        )
        if b" 101 " not in headers.split(b"\r\n")[0] or expected not in headers:
            raise ValueError("CDP handshake rejected")
        self.sequence = 0

    def read(self, length):
        data = bytearray()
        while len(data) < length:
            part = self.sock.recv(length - len(data))
            if not part:
                raise ConnectionError("Client debugger closed")
            data.extend(part)
        return bytes(data)

    def send(self, payload, opcode=1):
        mask = os.urandom(4)
        n = len(payload)
        head = bytes([128 | opcode])
        head += (
            bytes([128 | n])
            if n < 126
            else (
                bytes([254]) + struct.pack("!H", n)
                if n < 65536
                else bytes([255]) + struct.pack("!Q", n)
            )
        )
        self.sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def receive(self):
        data = bytearray()
        while True:
            first, second = self.read(2)
            n = second & 127
            if n in (126, 127):
                n = struct.unpack("!H" if n == 126 else "!Q", self.read(2 if n == 126 else 8))[0]
            if second & 128 or n > 8 * 1024 * 1024 or len(data) + n > 8 * 1024 * 1024:
                raise ValueError("Invalid CDP frame")
            part = self.read(n)
            opcode = first & 15
            if opcode == 8:
                raise ConnectionError("CDP closed")
            if opcode == 9:
                self.send(part, 10)
                continue
            if opcode == 10:
                continue
            data.extend(part)
            if first & 128:
                return json.loads(data)

    def call(self, method, params=None):
        self.sequence += 1
        self.send(
            json.dumps({"id": self.sequence, "method": method, "params": params or {}}).encode()
        )
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            result = self.receive()
            if result.get("id") == self.sequence:
                if "error" in result:
                    raise RuntimeError("Client debugger command failed")
                return result["result"]
        raise TimeoutError("Client debugger did not finish")

    def evaluate(self, expression):
        result = self.call(
            "Runtime.evaluate",
            {"expression": expression, "awaitPromise": True, "returnByValue": True},
        )
        if "exceptionDetails" in result:
            raise RuntimeError("Native acceptance assertion failed")
        return result.get("result", {}).get("value")

    def close(self):
        self.sock.close()
