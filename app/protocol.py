import json

def build_message(msg_type, **kwargs):
    message = {"type": msg_type}
    message.update(kwargs)
    return json.dumps(message).encode('utf-8')

def parse_message(data):
    try:
        return json.loads(data.decode('utf-8'))
    except json.JSONDecodeError:
        return None