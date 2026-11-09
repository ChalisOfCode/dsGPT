"""Private length-delimited IPC. Never log frames or accept raw CDP commands."""

import base64
import json
import struct

from .account_browser_profile_data import MAX_ENVELOPE, validate

MAX_FRAME = MAX_ENVELOPE + 65536


class BrowserWireError(Exception):
    pass


def pack(value):
    data = json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode()
    if not 0 < len(data) <= MAX_FRAME:
        raise BrowserWireError("account_browser_frame_limit")
    return struct.pack("!I", len(data)) + data


def size(header):
    length = struct.unpack("!I", header)[0]
    if not 0 < length <= MAX_FRAME:
        raise BrowserWireError("account_browser_frame_limit")
    return length


def receive(stream):
    def exact(count):
        data = bytearray()
        while len(data) < count:
            chunk = stream.read(count - len(data))
            if not chunk:
                raise BrowserWireError("account_browser_pipe_closed")
            data.extend(chunk)
        return bytes(data)

    return json.loads(exact(size(exact(4))))


def encode_files(files):
    if files is None:
        return None
    validate(files)
    return {name: base64.b64encode(data).decode("ascii") for name, data in files.items()}


def decode_files(files):
    if files is None:
        return None
    if type(files) is not dict:
        raise BrowserWireError("account_browser_profile_invalid")
    result = {name: base64.b64decode(data, validate=True) for name, data in files.items()}
    validate(result)
    return result
