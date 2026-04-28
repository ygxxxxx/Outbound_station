from src.utils.logger import logger
from datetime import datetime
import json

logger = logger.bind(tag="RCSProtocol")
SEPARATOR = b'\n'

# 编码函数
def encode(body_dict: dict) -> bytes:
    body_json = json.dumps(body_dict, ensure_ascii=False).encode('utf-8')
    return body_json + SEPARATOR

# 解码函数
def decode(data: bytes) -> tuple[dict | None, bytes]:
    if SEPARATOR not in data:
        return None, data
    line, remain  = data.split(SEPARATOR, 1)
    try:
        return json.loads(line.decode('utf-8')), remain 
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, remain 
    
def build_message(msg_type: str, sender: str, receiver: str, data: dict) -> bytes:
    message = {
        "type": msg_type,
        "sender": sender,
        "receiver": receiver,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data": data
    }
    return encode(message)