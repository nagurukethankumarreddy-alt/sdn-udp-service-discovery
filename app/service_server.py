
import socket
import threading
import time
import argparse
from protocol import build_message, parse_message

def send_heartbeats(sock, reg_ip, reg_port, service, my_ip, my_port):
    while True:
        msg = build_message("HEARTBEAT", service=service, ip=my_ip, port=my_port)
        sock.sendto(msg, (reg_ip, reg_port))
        time.sleep(2)

def start_server(my_ip, my_port, reg_ip, reg_port, service):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((my_ip, my_port))
    
    reg_msg = build_message("REGISTER", service=service, ip=my_ip, port=my_port)
    sock.sendto(reg_msg, (reg_ip, reg_port))
    print(f"Service Server '{service}' running on {my_ip}:{my_port}")
    
    threading.Thread(target=send_heartbeats, args=(sock, reg_ip, reg_port, service, my_ip, my_port), daemon=True).start()
    
    while True:
        data, addr = sock.recvfrom(1024)
        msg = parse_message(data)
        if msg and msg['type'] == 'SERVICE_REQUEST':
            print(f"[REQUEST] Received workload from {addr}")
            resp = build_message("SERVICE_RESPONSE", data="Processed UDP payload successfully")
            sock.sendto(resp, addr)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--ip', required=True, help='This server IP')
    parser.add_argument('--port', type=int, default=8001)
    parser.add_argument('--reg-ip', default='10.0.0.1', help='Registry IP')
    parser.add_argument('--reg-port', type=int, default=5000)
    parser.add_argument('--service', default='compute')
    args = parser.parse_args()
    start_server(args.ip, args.port, args.reg_ip, args.reg_port, args.service)
