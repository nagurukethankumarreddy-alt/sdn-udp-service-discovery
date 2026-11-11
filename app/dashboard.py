"""Interactive web application for UDP service discovery and provider management.

Run as a module from the project root:
  python3 -m app.dashboard --registry-ip 10.0.0.1 --controller-url http://127.0.0.1:8080

The dashboard binds to localhost by default. Provider agents are started in Mininet
by topology/mininet_topology.py and allow the UI to start/stop service_server.py
processes inside the selected Mininet host namespace.
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.protocol import DISCOVER, SERVICE_REQUEST, decode_message, encode_message  # noqa: E402
from app.selection import controller_select, order_candidates  # noqa: E402


def parse_provider_hosts(raw: str) -> List[Dict[str, str]]:
    """Parse host=ip pairs, e.g. h2=10.0.0.2,h3=10.0.0.3."""
    hosts = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"invalid provider host mapping: {part}")
        name, ip = part.split("=", 1)
        name, ip = name.strip(), ip.strip()
        if not name or not ip:
            raise ValueError(f"invalid provider host mapping: {part}")
        hosts.append({"name": name, "ip": ip})
    return hosts


def udp_exchange(host: str, port: int, message: Dict[str, Any], timeout: float = 1.5) -> Dict[str, Any]:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.sendto(encode_message(message), (host, int(port)))
        payload, _ = sock.recvfrom(65535)
        return decode_message(payload)


def http_json(url: str, method: str = "GET", payload: Optional[Dict[str, Any]] = None,
              timeout: float = 0.8) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            details = json.loads(exc.read().decode("utf-8"))
        except Exception:
            details = {"error": str(exc)}
        raise RuntimeError(details.get("error") or details.get("message") or str(exc)) from exc
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(str(exc)) from exc


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SDN Service Discovery</title>
<style>
:root{font-family:Inter,system-ui,Arial,sans-serif;color:#17243a;background:#f3f6fb}
*{box-sizing:border-box}body{margin:0}header{background:linear-gradient(115deg,#10233f,#1d4775);color:#fff;padding:25px max(20px,calc((100% - 1160px)/2))}
header h1{margin:0 0 7px;font-size:26px}header p{margin:0;color:#c9d8eb;font-size:14px}
main{max-width:1160px;margin:24px auto;padding:0 18px}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:13px}
.card{background:#fff;border:1px solid #e1e8f1;border-radius:14px;padding:17px;box-shadow:0 5px 18px #14213a08}
.metric-label{font-size:12px;color:#68778d;font-weight:650}.metric{font-size:25px;font-weight:760;margin-top:5px}
.tabs{display:flex;gap:7px;margin:19px 0 13px;flex-wrap:wrap}.tab{border:1px solid #d4dfed;background:#fff;color:#234062;border-radius:9px;padding:10px 15px;font-weight:700;cursor:pointer}
.tab.active{background:#1f5798;color:#fff;border-color:#1f5798}
.panel{display:none}.panel.active{display:block}.layout{display:grid;grid-template-columns: minmax(0,1fr) minmax(0,1fr);gap:14px}
h2{font-size:18px;margin:0 0 6px}.sub{font-size:13px;color:#718096;margin-bottom:13px}
label{display:block;font-size:13px;font-weight:700;margin:12px 0 6px}
input,select,textarea{width:100%;padding:10px 11px;border:1px solid #cbd5e1;border-radius:9px;font:inherit;background:white;color:#17243a}
textarea{min-height:82px;resize:vertical}.form-row{display:grid;grid-template-columns:1fr 1fr;gap:10px}
button{border:0;border-radius:9px;background:#20599b;color:#fff;padding:10px 14px;font-weight:700;cursor:pointer;margin:12px 7px 0 0}
button:hover{filter:brightness(.96)}button.secondary{background:#e8eef7;color:#234062}button.danger{background:#a93434}
button:disabled{opacity:.5;cursor:not-allowed}
.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;margin-top:8px;font-size:13px}
th,td{text-align:left;padding:10px 8px;border-bottom:1px solid #edf1f6;white-space:nowrap}th{color:#718096;font-weight:700}
.pill{display:inline-block;padding:4px 8px;border-radius:20px;font-size:11px;font-weight:800}
.active-pill{background:#dcfce7;color:#166534}.inactive-pill{background:#fee2e2;color:#991b1b}.unknown-pill{background:#edf2f7;color:#526176}
pre{white-space:pre-wrap;word-break:break-word;background:#101b2c;color:#dbe8f8;padding:13px;border-radius:10px;min-height:80px;font-size:12px}
.notice{font-size:13px;color:#526176;margin-top:10px;min-height:18px}.small{font-size:12px;color:#78869a}
.provider-choice{border:1px solid #dbe4ef;border-radius:9px;padding:10px;margin:8px 0;display:flex;align-items:center;gap:9px}
.provider-choice input{width:auto}.provider-choice .grow{flex:1}.empty{color:#8290a4;font-size:13px;padding:12px 0}
@media(max-width:800px){.metrics{grid-template-columns:repeat(2,1fr)}.layout{grid-template-columns:1fr}}
@media(max-width:480px){.metrics{grid-template-columns:1fr 1fr}.form-row{grid-template-columns:1fr}}
</style></head>
<body>
<header><h1>SDN-integrated UDP Service Discovery</h1><p>Manage service providers · Discover services as a client · Observe registry and Ryu status</p></header>
<main>
<section class="metrics">
 <div class="card"><div class="metric-label">UDP REGISTRY</div><div class="metric" id="registry-status">Checking</div><div class="small">10.0.0.1:9999</div></div>
 <div class="card"><div class="metric-label">RYU CONTROLLER</div><div class="metric" id="ryu-status">Checking</div><div class="small">REST API · OpenFlow 1.3</div></div>
 <div class="card"><div class="metric-label">ACTIVE PROVIDERS</div><div class="metric" id="active-count">—</div><div class="small">Registered service endpoints</div></div>
 <div class="card"><div class="metric-label">PROVIDER AGENTS</div><div class="metric" id="agent-count">—</div><div class="small">Mininet hosts manageable from UI</div></div>
</section>

<nav class="tabs">
 <button class="tab active" data-tab="client-panel">Client</button>
 <button class="tab" data-tab="provider-panel">Service Provider</button>
 <button class="tab" data-tab="network-panel">Network Status</button>
</nav>

<section id="client-panel" class="panel active">
 <div class="layout">
  <div class="card">
   <h2>Discover a service</h2><div class="sub">Search the UDP registry for all active providers of a service.</div>
   <label for="client-service">Service name</label>
   <input id="client-service" list="service-options" value="Weather" placeholder="e.g. Weather, News, Maps">
   <datalist id="service-options"><option value="Weather"><option value="News"></datalist>
   <button id="discover-button">Discover servers</button>
   <div id="discover-note" class="notice">Enter a service name and discover available providers.</div>
   <div id="provider-choices"><div class="empty">No discovery results yet.</div></div>
  </div>
  <div class="card">
   <h2>Send a service request</h2><div class="sub">Select a discovered provider or let Ryu choose one automatically.</div>
   <label for="request-message">Request message</label>
   <textarea id="request-message">Please process my service request.</textarea>
   <label for="selection-mode">Provider selection</label>
   <select id="selection-mode"><option value="sdn">Ryu-assisted selection</option><option value="manual">Use selected provider</option><option value="registry">Registry-first selection</option></select>
   <button id="send-button">Send UDP request</button>
   <div id="request-note" class="notice">Discover a service before sending a request.</div>
   <h2 style="margin-top:18px">Request / response</h2><pre id="client-output">The server response will appear here.</pre>
  </div>
 </div>
</section>

<section id="provider-panel" class="panel">
 <div class="layout">
  <div class="card">
   <h2>Add a service provider</h2>
   <div class="sub">Start a real UDP service process inside one of the available Mininet hosts.</div>
   <label for="provider-service">Service provided</label>
   <input id="provider-service" list="service-options" placeholder="e.g. Weather, News, Maps" value="News">
   <div class="form-row">
    <div><label for="provider-host">Mininet host</label><select id="provider-host"></select></div>
    <div><label for="provider-port">UDP service port</label><input id="provider-port" type="number" min="1" max="65535" value="5010"></div>
   </div>
   <div class="form-row">
    <div><label for="provider-delay">Response delay (ms)</label><input id="provider-delay" type="number" min="0" value="0"></div>
    <div><label for="provider-drop">Drop every Nth request</label><input id="provider-drop" type="number" min="0" value="0"></div>
   </div>
   <button id="start-provider">Add / start server</button>
   <div id="provider-note" class="notice">Choose a host, service name and UDP port.</div>
   <p class="small">The topology pre-creates h2–h5. This form starts/stops service-provider processes on those hosts; it does not add new Mininet hosts dynamically.</p>
  </div>
  <div class="card">
   <h2>Managed service providers</h2><div class="sub">Providers started through this dashboard can be stopped here.</div>
   <div class="table-wrap"><table><thead><tr><th>Host</th><th>Service</th><th>IP:Port</th><th>State</th><th></th></tr></thead><tbody id="managed-servers"><tr><td colspan="5">Loading...</td></tr></tbody></table></div>
   <button class="secondary" id="refresh-managed">Refresh provider list</button>
  </div>
 </div>
</section>

<section id="network-panel" class="panel">
 <div class="layout">
  <div class="card"><h2>Registered services</h2><div class="sub">Live state read from the UDP registry.</div>
   <div class="table-wrap"><table><thead><tr><th>Service</th><th>Provider</th><th>Port</th><th>Status</th></tr></thead><tbody id="registry-servers"><tr><td colspan="4">Loading...</td></tr></tbody></table></div>
   <button class="secondary" id="refresh-status">Refresh status</button>
  </div>
  <div class="card"><h2>Network and controller</h2><div class="sub">Ryu controller status and provider-agent availability.</div>
   <pre id="network-output">Loading...</pre>
  </div>
 </div>
</section>
</main>
<script>
let latestProviders = [];
let latestStatus = null;
let selectedProviderKey = '';
const $ = id => document.getElementById(id);
function setText(id, value){$(id).textContent=value;}
async function api(path, body){
 const options = body===undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)};
 const response = await fetch(path, options);
 const payload = await response.json();
 if(!response.ok) throw new Error(payload.error || payload.message || `HTTP ${response.status}`);
 return payload;
}
function setNotice(id, message, bad=false){$(id).textContent=message;$(id).style.color=bad?'#a93434':'#526176';}
function pill(status){
 const span=document.createElement('span');span.className='pill '+(status==='ACTIVE'||status==='RUNNING'?'active-pill':status==='INACTIVE'||status==='STOPPED'||status==='FAILED'?'inactive-pill':'unknown-pill');span.textContent=status||'UNKNOWN';return span;
}
function cell(row, value){const td=document.createElement('td');td.textContent=value??'';row.appendChild(td);return td;}
function switchTab(id){
 document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('active',b.dataset.tab===id));
 document.querySelectorAll('.panel').forEach(p=>p.classList.toggle('active',p.id===id));
 if(id==='provider-panel')refreshManaged();
 if(id==='network-panel')refreshStatus();
}
document.querySelectorAll('.tab').forEach(b=>b.addEventListener('click',()=>switchTab(b.dataset.tab)));

async function refreshStatus(){
 try{
  const s=await api('/api/status');latestStatus=s;
  setText('registry-status',s.registry_ok?'Online':'Offline');
  setText('ryu-status',s.ryu_ok?'Connected':'Offline');
  setText('active-count',String(s.active_count??0));
  const agents=s.agents||[];setText('agent-count',`${agents.filter(a=>a.ok).length}/${agents.length}`);
  const body=$('registry-servers');body.replaceChildren();
  const services=s.services||{};
  for(const [service,providers] of Object.entries(services)){
   for(const provider of providers){
    const row=document.createElement('tr');cell(row,service);cell(row,provider.ip);cell(row,provider.port);row.appendChild(cell(row,'').appendChild(pill(provider.status)).parentElement);body.appendChild(row);
   }
  }
  if(!body.children.length){const row=document.createElement('tr');cell(row,'No providers registered');const td=document.createElement('td');td.colSpan=3;row.appendChild(td);body.appendChild(row);}
  const network={controller:s.controller,agents:agents,registry_error:s.registry_error||null};
  $('network-output').textContent=JSON.stringify(network,null,2);
  const names=Object.keys(services);
  const datalist=$('service-options');datalist.replaceChildren();
  [...new Set(['Weather','News',...names])].forEach(name=>{const option=document.createElement('option');option.value=name;datalist.appendChild(option);});
 }catch(err){setText('registry-status','Error');setNotice('discover-note',err.message,true);}
}

async function discover(){
 const service=$('client-service').value.trim();
 if(!service){setNotice('discover-note','Enter a service name.',true);return;}
 setNotice('discover-note',`Searching registry for ${service}...`);
 $('provider-choices').replaceChildren();
 try{
  const result=await api('/api/discover',{service,selection_mode:$('selection-mode').value});
  latestProviders=result.providers||[];
  const selected=result.selected_provider;
  selectedProviderKey=selected?`${selected.ip}:${selected.port}`:'';
  setNotice('discover-note',`${latestProviders.length} active provider(s) found. Policy: ${result.selection_policy}.`);
  latestProviders.forEach((provider,index)=>{
   const wrap=document.createElement('label');wrap.className='provider-choice';
   const radio=document.createElement('input');radio.type='radio';radio.name='provider-choice';radio.value=`${provider.ip}:${provider.port}`;
   radio.checked=radio.value===selectedProviderKey;
   radio.addEventListener('change',()=>{selectedProviderKey=radio.value;});
   const content=document.createElement('span');content.className='grow';
   content.textContent=`${provider.ip}:${provider.port} · ${provider.status||'ACTIVE'}`;
   const defaultTag=document.createElement('span');defaultTag.className='small';defaultTag.textContent=radio.checked?'Ryu selected':'';
   wrap.append(radio,content,defaultTag);$('provider-choices').appendChild(wrap);
  });
  if(!latestProviders.length){$('provider-choices').textContent='No active providers.';}
  await refreshStatus();
 }catch(err){setNotice('discover-note',err.message,true);$('provider-choices').textContent='No discovery results.';}
}

async function sendRequest(){
 const service=$('client-service').value.trim();
 if(!service){setNotice('request-note','Enter a service name first.',true);return;}
 if(!latestProviders.length){await discover();if(!latestProviders.length)return;}
 const mode=$('selection-mode').value;
 const body={service,message:$('request-message').value,selection_mode:mode};
 if(mode==='manual'){
  const chosen=document.querySelector('input[name="provider-choice"]:checked');
  if(!chosen){setNotice('request-note','Select a discovered provider first.',true);return;}
  const [ip,port]=chosen.value.split(':');body.provider={ip,port:Number(port)};
 }
 setNotice('request-note','Sending UDP service request...');
 try{
  const result=await api('/api/request',body);
  $('client-output').textContent=JSON.stringify(result,null,2);
  setNotice('request-note',`Success from ${result.selected_provider.ip}:${result.selected_provider.port} in ${result.elapsed_ms} ms. Fallback used: ${result.fallback_used?'yes':'no'}.`);
  await refreshStatus();
 }catch(err){setNotice('request-note',err.message,true);$('client-output').textContent=JSON.stringify({error:err.message},null,2);}
}

function renderManaged(servers){
 const body=$('managed-servers');body.replaceChildren();
 if(!servers.length){const row=document.createElement('tr');const td=document.createElement('td');td.colSpan=5;td.textContent='No providers started from this dashboard yet.';row.appendChild(td);body.appendChild(row);return;}
 servers.forEach(server=>{
  const row=document.createElement('tr');cell(row,server.host);cell(row,server.service);cell(row,`${server.ip}:${server.port}`);
  const state=cell(row,'');state.appendChild(pill(server.status));
  const actions=cell(row,'');
  if(server.status==='RUNNING'){
   const button=document.createElement('button');button.className='danger';button.textContent='Stop';button.style.margin='0';
   button.addEventListener('click',()=>stopProvider(server.host,server.port));actions.appendChild(button);
  }
  body.appendChild(row);
 });
}
async function refreshManaged(){
 try{
  const result=await api('/api/managed');
  renderManaged(result.servers||[]);
  const select=$('provider-host');const current=select.value;select.replaceChildren();
  (result.agents||[]).forEach(agent=>{
   const option=document.createElement('option');option.value=agent.name;option.textContent=`${agent.name} · ${agent.ip} · ${agent.ok?'available':'offline'}`;option.disabled=!agent.ok;select.appendChild(option);
  });
  if(current)select.value=current;
 }catch(err){setNotice('provider-note',err.message,true);}
}
async function startProvider(){
 const body={
  host:$('provider-host').value,service:$('provider-service').value.trim(),
  port:Number($('provider-port').value),
  response_delay_ms:Number($('provider-delay').value||0),
  drop_every:Number($('provider-drop').value||0)
 };
 if(!body.service){setNotice('provider-note','Enter the service name this server provides.',true);return;}
 setNotice('provider-note','Starting provider and registering it with the UDP registry...');
 try{
  const result=await api('/api/provider/start',body);
  setNotice('provider-note',`Started ${result.service} on ${result.host} (${result.ip}:${result.port}); registry registration sent.`);
  await refreshManaged();await refreshStatus();
 }catch(err){setNotice('provider-note',err.message,true);}
}
async function stopProvider(host,port){
 setNotice('provider-note',`Stopping ${host} service on UDP port ${port}...`);
 try{const result=await api('/api/provider/stop',{host,port});setNotice('provider-note',`Stopped ${result.service} on ${host}; graceful unregister sent.`);await refreshManaged();await refreshStatus();}
 catch(err){setNotice('provider-note',err.message,true);}
}
$('discover-button').addEventListener('click',discover);
$('send-button').addEventListener('click',sendRequest);
$('start-provider').addEventListener('click',startProvider);
$('refresh-managed').addEventListener('click',refreshManaged);
$('refresh-status').addEventListener('click',refreshStatus);
refreshStatus();refreshManaged();setInterval(refreshStatus,6000);
</script>
</body></html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    config: Dict[str, Any] = {}

    def _send(self, status: int, payload: Any, content_type: str = "application/json"):
        data = payload.encode("utf-8") if isinstance(payload, str) else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type + ("; charset=utf-8" if content_type.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 16_384:
            raise ValueError("request body too large")
        body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        if not isinstance(body, dict):
            raise ValueError("JSON body must be an object")
        return body

    @classmethod
    def _cfg(cls):
        return cls.config

    def _registry_status(self):
        cfg = self._cfg()
        return udp_exchange(
            cfg["registry_ip"], cfg["registry_port"], {"type": "STATUS"}, cfg["timeout"]
        )

    def _agent_url(self, host_name: str):
        cfg = self._cfg()
        mapping = {host["name"]: host["ip"] for host in cfg["provider_hosts"]}
        if host_name not in mapping:
            raise ValueError(f"unknown provider host: {host_name}")
        return f"http://{mapping[host_name]}:{cfg['agent_port']}"

    def _agent_get(self, host_name: str, path: str):
        return http_json(self._agent_url(host_name) + path, timeout=self._cfg()["timeout"])

    def _agent_post(self, host_name: str, path: str, payload: Dict[str, Any]):
        return http_json(
            self._agent_url(host_name) + path, method="POST", payload=payload,
            timeout=max(2.0, self._cfg()["timeout"]),
        )

    def _all_agents(self):
        agents = []
        for host in self._cfg()["provider_hosts"]:
            try:
                health = self._agent_get(host["name"], "/health")
                agents.append({"name": host["name"], "ip": host["ip"], "ok": True, "detail": health})
            except Exception as exc:
                agents.append({"name": host["name"], "ip": host["ip"], "ok": False, "error": str(exc)})
        return agents

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            self._send(200, PAGE, "text/html")
            return
        if self.path == "/api/status":
            registry = None
            controller = None
            registry_error = None
            ryu_error = None
            try:
                registry = self._registry_status()
            except Exception as exc:
                registry_error = str(exc)
            if self._cfg()["controller_url"]:
                try:
                    controller = http_json(
                        self._cfg()["controller_url"].rstrip("/") + "/service/status",
                        timeout=self._cfg()["timeout"],
                    )
                except Exception as exc:
                    ryu_error = str(exc)
            services = registry.get("services", {}) if registry else {}
            active_count = sum(
                1 for records in services.values()
                for record in records if record.get("status") == "ACTIVE"
            )
            self._send(200, {
                "registry_ok": registry is not None,
                "ryu_ok": controller is not None,
                "active_count": active_count,
                "services": services,
                "controller": controller,
                "agents": self._all_agents(),
                "registry_error": registry_error,
                "ryu_error": ryu_error,
            })
            return
        if self.path == "/api/managed":
            managed = []
            agents = self._all_agents()
            for agent in agents:
                if agent["ok"]:
                    try:
                        result = self._agent_get(agent["name"], "/servers")
                        managed.extend(result.get("servers", []))
                    except Exception:
                        pass
            self._send(200, {"agents": agents, "servers": managed})
            return
        self._send(404, {"error": "not found"})

    def do_POST(self):
        try:
            body = self._body()
            cfg = self._cfg()

            if self.path == "/api/provider/start":
                host = str(body.get("host", "")).strip()
                service = str(body.get("service", "")).strip()
                port = int(body.get("port", 0))
                if not service or len(service) > 64:
                    raise ValueError("enter a service name between 1 and 64 characters")
                if not 1 <= port <= 65535:
                    raise ValueError("UDP service port must be between 1 and 65535")
                result = self._agent_post(host, "/start", {
                    "service": service, "port": port,
                    "response_delay_ms": int(body.get("response_delay_ms", 0)),
                    "drop_every": int(body.get("drop_every", 0)),
                    "workers": int(body.get("workers", 8)),
                })
                self._send(201, result)
                return

            if self.path == "/api/provider/stop":
                host = str(body.get("host", "")).strip()
                result = self._agent_post(host, "/stop", {"port": int(body.get("port", 0))})
                self._send(200, result)
                return

            if self.path in ("/api/discover", "/api/request"):
                service = str(body.get("service", "")).strip()
                if not service or len(service) > 64:
                    raise ValueError("service name must contain 1–64 characters")
                discovery = udp_exchange(
                    cfg["registry_ip"], cfg["registry_port"],
                    {"type": DISCOVER, "service": service}, cfg["timeout"]
                )
                servers = discovery.get("servers", [])
                if discovery.get("status") != "OK" or not servers:
                    self._send(404, {"error": f"No active provider registered for '{service}'", "discovery": discovery})
                    return

                selection_mode = str(body.get("selection_mode", "sdn"))
                preferred = None
                if selection_mode == "sdn" and cfg["controller_url"]:
                    preferred = controller_select(cfg["controller_url"], service, cfg["timeout"])
                candidates = order_candidates(servers, preferred)

                if selection_mode == "manual":
                    requested = body.get("provider") or {}
                    key = (str(requested.get("ip", "")), int(requested.get("port", 0)))
                    index = next((
                        i for i, provider in enumerate(candidates)
                        if (str(provider["ip"]), int(provider["port"])) == key
                    ), None)
                    if index is None:
                        raise ValueError("selected provider is not in the active discovery results")
                    candidates = candidates[index:] + candidates[:index]
                elif selection_mode == "registry":
                    candidates = list(servers)
                elif selection_mode not in ("sdn", "manual", "registry"):
                    raise ValueError("selection_mode must be sdn, manual or registry")

                if self.path == "/api/discover":
                    selected = candidates[0]
                    self._send(200, {
                        "service": service, "providers": servers,
                        "selection_policy": (
                            "Ryu round-robin" if preferred else
                            "manual provider preference" if selection_mode == "manual" else
                            "registry-first" if selection_mode == "registry" else
                            "registry-first fallback (Ryu unavailable)"
                        ),
                        "selected_provider": selected,
                    })
                    return

                message = str(body.get("message", "Dashboard request"))[:512]
                errors = []
                started = time.perf_counter()
                for provider in candidates:
                    try:
                        reply = udp_exchange(
                            provider["ip"], int(provider["port"]),
                            {"type": SERVICE_REQUEST, "service": service, "message": message},
                            cfg["timeout"],
                        )
                        elapsed_ms = (time.perf_counter() - started) * 1000.0
                        self._send(200, {
                            "service": service, "selected_provider": provider,
                            "selection_policy": (
                                "Ryu round-robin" if preferred else
                                "manual provider preference" if selection_mode == "manual" else
                                "registry-first"
                            ),
                            "elapsed_ms": round(elapsed_ms, 3), "response": reply,
                            "fallback_used": bool(errors), "provider_errors": errors,
                        })
                        return
                    except (OSError, ValueError) as exc:
                        errors.append(f"{provider['ip']}:{provider['port']}: {exc}")
                self._send(502, {"error": "all active providers failed", "provider_errors": errors})
                return

            self._send(404, {"error": "not found"})
        except (ValueError, TypeError, RuntimeError, OSError) as exc:
            self._send(400, {"error": str(exc)})

    def log_message(self, fmt, *args):
        print("[DASHBOARD] " + fmt % args, flush=True)


def main():
    parser = argparse.ArgumentParser(description="Interactive UDP service discovery dashboard")
    parser.add_argument("--host", default="127.0.0.1", help="dashboard bind address (localhost by default)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--registry-ip", default="10.0.0.1")
    parser.add_argument("--registry-port", type=int, default=9999)
    parser.add_argument("--controller-url", default="http://127.0.0.1:8080")
    parser.add_argument("--agent-port", type=int, default=8765)
    parser.add_argument("--provider-hosts", default="h2=10.0.0.2,h3=10.0.0.3,h4=10.0.0.4,h5=10.0.0.5")
    parser.add_argument("--timeout", type=float, default=1.5)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or not 1 <= args.registry_port <= 65535 or args.timeout <= 0:
        raise SystemExit("invalid port or timeout")
    cfg = vars(args).copy()
    cfg["provider_hosts"] = parse_provider_hosts(args.provider_hosts)
    DashboardHandler.config = cfg
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"[DASHBOARD] Running at http://{args.host}:{args.port}", flush=True)
    print("[DASHBOARD] Start Mininet first so provider agents are available.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[DASHBOARD] Stopping", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
