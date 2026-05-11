from src.utils.logger import logger
from src.exception.exception import ProtocolDataError,ProtocolVersionError
import json
import struct

logger = logger.bind(tag="RCSProtocol")

MAGIC = 0xAC
PROTOCOL_VERSION = 1

HEADER_SIZE = 10  # 1同步字节 + 1协议版本 + 2序号 + 2报文类型编码 + 4数据长度 

def encode(seq: int, cmd: int, body_dict: dict|None = None) -> bytes:
    body_json = b''
    if body_dict is not None:
        body_json = json.dumps(body_dict, ensure_ascii = False).encode('utf-8')
        header = struct.pack('>BBHHI', MAGIC, PROTOCOL_VERSION, seq, cmd, len(body_json))
    else:
        header = struct.pack('>BBHHI', MAGIC, PROTOCOL_VERSION, seq, cmd, 0x00000000)
    return header + body_json

def decode(buffer: bytes) -> tuple[None, bytes] | tuple[tuple[int, int, dict | None], bytes]:
    if len(buffer) < HEADER_SIZE:
        return None, buffer
    magic, protocol_version, seq, cmd, body_len = struct.unpack('>BBHHI', buffer[:HEADER_SIZE])
    if magic != MAGIC:
        idx = 2
        while idx < len(buffer):
            check = struct.unpack('>B', buffer[idx:idx + 1])[0]
            if check == MAGIC:
                buffer = buffer[idx:]
                break
            idx += 1
        else:
            return None, b''
        magic, protocol_version, seq, cmd, body_len = struct.unpack('>BBHHI', buffer[:HEADER_SIZE])
    if protocol_version != PROTOCOL_VERSION:
        logger.error("协议版本错误")
        remaining = buffer[HEADER_SIZE:] # 版本错误时只消费了头部，跳过头部
        raise ProtocolVersionError(f"协议版本错误: {protocol_version}", seq = seq, cmd = cmd, remaining = remaining)
    total_len = HEADER_SIZE + body_len
    if len(buffer) < total_len:
        return None, buffer
    body_bytes = buffer[HEADER_SIZE:total_len]
    body_dict = None
    if body_len > 0:
        try:
            body_dict = json.loads(body_bytes.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error(f"数据解析错误: {e}")
            remaining = buffer[total_len:]  # 数据体长度已知，跳过整个包
            raise ProtocolDataError(f"数据解析错误: {e}", seq = seq, cmd = cmd, remaining = remaining)
    remaining = buffer[total_len:]
    return (seq, cmd, body_dict), remaining