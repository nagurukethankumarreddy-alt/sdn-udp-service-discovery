import socket
import threading
import time
import requests
import argparse
from protocol import parse_message, build_message

SDN_CONTROLLER_URL = 'http://127.0.0.1:8080/sdn/service'
registry = {}
lock = threading.Lock()

def notify_sdn(action, ip, port):
    try:
        requests.post(f"{SDN_CONTROLLER_URL}/{action}", json={"ip": ip, "port": port}, timeout=1)
    except requests.exceptions.RequestException:
        pass # Fails safely if Ryu is not running

def heartbeat_reaper():
    while True:
        time.sleep(2)
        current_time = time.time()
        with lock:
            for service, servers in list(registry.items()):
                for endpoint, data in list(servers.items()):
                    if current_time - data['last_heartbeat'] > 6.0:
                        print(f"[TIMEOUT] {endpoint} marked UNAVAILABLE")
                        notify_sdn("revoke", data['ip'], data['port'])
                        del servers[endpoint]

def start_registry(host_ip, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((host_ip, port))
    print(f"Registry Server listening on {host_ip}:{port}")
    
    threading.Thread(target=heartbeat_reaper, daemon=True).start()

    while True:
        data, addr = sock.recvfrom(1024)
        msg = parse_message(data)
        if not msg: continue
        
        with lock:
            if msg['type'] in ['REGISTER', 'HEARTBEAT']:
                service = msg['service']
                ip, s_port = msg['ip'], msg['port']
                endpoint = f"{ip}:{s_port}"
                
                if service not in registry:
                    registry[service] = {}
                
                if endpoint not in registry[service]:
                    print(f"[REGISTER] New service {service} at {endpoint}")
                    notify_sdn("register", ip, s_port)
                
                registry[service][endpoint] = {
                    "ip": ip, "port": s_port, "last_heartbeat": time.time(), "status": "ACTIVE"
                }
                
                if msg['type'] == 'REGISTER':
                    sock.sendto(build_message("REGISTER_ACK", status="OK"), addr)
                    
            elif msg['type'] == 'DISCOVER':
                service = msg['service']
                servers = registry.get(service, {})
                if servers:
                    best_server = list(servers.values())[0]
                    sock.sendto(build_message("DISCOVER_RESP", status="OK", ip=best_server['ip'], port=best_server['port']), addr)
                else:
                    sock.sendto(build_message("DISCOVER_RESP", status="FAIL"), addr)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--ip', default='10.0.0.1', help='Registry IP in Mininet')
    parser.add_argument('--port', type=int, default=5000)
    args = parser.parse_args()
    start_registry(args.ip, args.port)