import socket
import argparse
from protocol import build_message, parse_message

def run_client(reg_ip, reg_port, service):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(3.0)
    
    print(f"Discovering '{service}' via Registry at {reg_ip}:{reg_port}...")
    req = build_message("DISCOVER", service=service)
    sock.sendto(req, (reg_ip, reg_port))
    
    try:
        data, _ = sock.recvfrom(1024)
        resp = parse_message(data)
        
        if resp and resp.get('status') == 'OK':
            server_ip = resp['ip']
            server_port = resp['port']
            print(f"Discovered server at {server_ip}:{server_port}")
            
            print("Sending SERVICE_REQUEST to server...")
            svc_req = build_message("SERVICE_REQUEST", payload="Client computing task")
            sock.sendto(svc_req, (server_ip, server_port))
            
            svc_data, _ = sock.recvfrom(1024)
            svc_resp = parse_message(svc_data)
            print(f"Received SERVICE_RESPONSE: {svc_resp}")
        else:
            print("Service not found in Registry.")
            
    except socket.timeout:
        print("Request timed out (Packet dropped).")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--reg-ip', default='10.0.0.1', help='Registry IP')
    parser.add_argument('--reg-port', type=int, default=5000)
    parser.add_argument('--service', default='compute')
    args = parser.parse_args()
    run_client(args.reg_ip, args.reg_port, args.service)