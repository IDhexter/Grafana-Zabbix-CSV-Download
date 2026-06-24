import sys
import os
import io
import csv
import json
import urllib.request
import ssl

# Auto-instala as dependencias se nao existirem
for lib in ["fastapi", "uvicorn"]:
    try:
        __import__(lib)
    except ImportError:
        import subprocess
        print(f"Instalando {lib}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", lib])

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import uvicorn

app = FastAPI(title="Zabbix API CSV Export Service")

# CONFIGURAÇÕES DA API DO ZABBIX - SUBISTITUA PELOS SEUS DADOS
TOKEN = "SEU_TOKEN_AQUI"
ZABBIX_API_URL = "http://IP_DO_SEU_ZABBIX/api_jsonrpc.php"

def call_zabbix_api(url, method, params, include_auth=True):
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1
    }
    data = json.dumps(payload).encode('utf-8')
    headers = {
        "Content-Type": "application/json"
    }
    if include_auth:
        headers["Authorization"] = f"Bearer {TOKEN}"
        
    ctx = ssl._create_unverified_context()
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20, context=ctx) as response:
            res = json.loads(response.read().decode('utf-8'))
            if 'result' in res:
                return res['result']
            else:
                print(f"[RESPOSTA API ERRO] Url: {url} - Resposta: {res}", file=sys.stderr)
                return None
    except Exception as e:
        print(f"[ERRO CONEXÃO API] Erro ao chamar {url} - {method}: {e}", file=sys.stderr)
        return None

@app.get("/exportar_csv")
def exportar_csv():
    # 1. Busca os Hosts
    hosts = call_zabbix_api(ZABBIX_API_URL, "host.get", {
        "output": ["hostid", "host", "name", "status", "proxy_hostid", "description"],
        "selectInterfaces": ["ip", "type", "port"],
        "selectHostGroups": ["name"],
        "selectParentTemplates": ["name"],
        "selectInventory": ["os", "hardware", "software", "serialno_a"]
    })
    
    if not hosts:
        return {"erro": "Falha ao conectar na API do Zabbix ou buscar hosts"}
        
    host_ids = [h['hostid'] for h in hosts]
    
    # 2. Busca Proxies
    proxies_map = {}
    proxies = call_zabbix_api(ZABBIX_API_URL, "proxy.get", {"output": ["proxyid", "name"]}) or []
    for p in proxies:
        proxies_map[str(p['proxyid'])] = p['name']
        
    # 3. Busca Alertas Ativos
    triggers_map = {}
    triggers = call_zabbix_api(ZABBIX_API_URL, "trigger.get", {
        "output": ["triggerid", "description", "priority"],
        "selectHosts": ["hostid"],
        "monitored": True,
        "only_true": True,
        "filter": {"value": 1}
    }) or []
    
    priorities = {"0": "Classif.", "1": "Info", "2": "Atencao", "3": "Media", "4": "Alta", "5": "Desastre"}
    for t in triggers:
        desc = t['description']
        priority_label = priorities.get(str(t['priority']), "Info")
        for h in t.get('hosts', []):
            hid = h['hostid']
            if hid not in triggers_map:
                triggers_map[hid] = []
            triggers_map[hid].append(f"[{priority_label.upper()}] {desc}")
            
    # 4. Busca Itens de Performance (Snapshot do Momento)
    items = call_zabbix_api(ZABBIX_API_URL, "item.get", {
        "hostids": host_ids,
        "output": ["hostid", "name", "key_", "lastvalue", "units"],
        "search": {
            "key_": [
                "cpu.util", "cpu.usage", "hrProcessorLoad", 
                "memory.util", "memory.size[pused]", "memory.used", 
                "pused",
                "system.sw.os", "system.descr", "system.uname",
                "system.hw.model", "system.hw.device",
                "system.uptime", "sysUpTimeInstance", "hrSystemUptime"
            ]
        },
        "searchByAny": True,
        "monitored": True
    }) or []
    
    host_items_map = {}
    for item in items:
        hid = item['hostid']
        if hid not in host_items_map:
            host_items_map[hid] = []
        host_items_map[hid].append(item)
        
    # 5. Processar Dados
    csv_rows = []
    colunas = [
        "ID do Host", "Nome Tecnico", "Nome Visivel", "Endereco IP", 
        "Modelo de Monitoramento", "Status (Ativo/Inativo)", "Proxy de Monitoramento",
        "CPU Ult. Valor", "Memoria Ult. Valor", "Discos (Uso %)", "Uptime", "Alertas Ativos no Ativo",
        "Grupos", "Templates Vinculados", "Sistema Operacional (OS)", "Hardware", "Numero de Serie", "Descricao"
    ]
    
    for host in hosts:
        hostid = host.get('hostid', '')
        hostname = host.get('host', '')
        name = host.get('name', '')
        status = "Ativo" if host.get('status') == "0" else "Inativo"
        
        proxy_id = str(host.get('proxy_hostid', ''))
        proxy_name = proxies_map.get(proxy_id, "Direto (Zabbix Server)") if proxy_id != "0" and proxy_id != "" else "Direto (Zabbix Server)"
        
        ips = [iface.get('ip', '') for iface in host.get('interfaces', []) if iface.get('ip')]
        ip_str = ", ".join(list(set(ips))) if ips else ""
        
        types = []
        for iface in host.get('interfaces', []):
            iftype = iface.get('type')
            if iftype == '1': types.append("Agente Zabbix")
            elif iftype == '2': types.append("SNMP")
            elif iftype == '3': types.append("IPMI")
            elif iftype == '4': types.append("JMX")
        type_str = ", ".join(list(set(types))) if types else "API / Sem Agente"
        
        groups = [g.get('name', '') for g in host.get('hostgroups', [])]
        groups_str = ", ".join(groups)
        
        templates = [t.get('name', '') for t in host.get('parentTemplates', [])]
        templates_str = ", ".join(templates)
        
        alertas_list = triggers_map.get(hostid, [])
        active_alerts = " | ".join(alertas_list) if alertas_list else "Sem Incidentes"
        
        host_desc = host.get('description', '') or ""
        host_desc = host_desc.replace("\n", " ").replace("\r", " ").strip()
        
        inventory = host.get('inventory')
        os_inv = inventory.get('os', '') if isinstance(inventory, dict) else ""
        hw_inv = inventory.get('hardware', '') if isinstance(inventory, dict) else ""
        serial = inventory.get('serialno_a', '') if isinstance(inventory, dict) else ""
        
        host_items = host_items_map.get(hostid, [])
        cpu_val, mem_val, disks, os_fallback, hw_fallback, uptime_val = "N/A", "N/A", [], "", "", "N/A"
        
        for item in host_items:
            key = item.get('key_', '')
            val = item.get('lastvalue', '') or ""
            units = item.get('units', '') or ""
            item_name = item.get('name', '')
            
            if val == "": continue
            
            if key in ["system.sw.os", "system.descr", "system.uname"]:
                if not os_fallback or key == "system.sw.os":
                    os_fallback = val
            if key in ["system.hw.model", "system.hw.device"]:
                hw_fallback = val
                
            try:
                val_float = float(val)
                val_str = f"{val_float:.2f}{units}" if units else f"{val_float:.2f}"
            except ValueError:
                val_str = f"{val}{units}" if units else f"{val}"
                
            if ("cpu.util" in key or "cpu.usage" in key or "hrProcessorLoad" in key) and not ("hrProcessorLoad[" in key):
                if cpu_val == "N/A" or "system.cpu.util" in key or "vm.cpu.util" in key:
                    cpu_val = val_str
            elif "memory.util" in key or "memory.size[pused]" in key or "memory.used" in key:
                if mem_val == "N/A" or "util" in key or "pused" in key:
                    mem_val = val_str
            elif "pused" in key:
                disk_label = key.split("[")[-1].split(",")[0].replace("]", "") if "[" in key else item_name
                disk_entry = f"{disk_label}: {val_str}"
                if disk_entry not in disks:
                    disks.append(disk_entry)
            elif "system.uptime" in key or "sysUpTimeInstance" in key or "hrSystemUptime" in key:
                try:
                    seconds = float(val)
                    if "SNMP" in type_str and units != "s" and units != "uptime":
                        seconds = seconds / 100.0
                    days = int(seconds // 86400)
                    hours = int((seconds % 86400) // 3600)
                    minutes = int((seconds % 3600) // 60)
                    uptime_val = f"{days}d {hours}h {minutes}m" if days > 0 else (f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m")
                except ValueError:
                    uptime_val = val
                    
        final_os = os_inv if os_inv else (os_fallback if os_fallback else "N/A")
        final_hw = hw_inv if hw_inv else (hw_fallback if hw_fallback else "N/A")
        final_os = final_os.replace("\n", " ").replace("\r", " ").strip()
        final_hw = final_hw.replace("\n", " ").replace("\r", " ").strip()
        disks_str = " | ".join(disks) if disks else "N/A"
        
        row_data = [
            hostid, hostname, name, ip_str, type_str, status, proxy_name,
            cpu_val, mem_val, disks_str, uptime_val, active_alerts, groups_str, templates_str,
            final_os, final_hw, serial, host_desc
        ]
        csv_rows.append(row_data)

    # 6. Gerar o CSV em memoria
    output = io.StringIO()
    output.write('\ufeff')  # BOM do UTF-8
    writer = csv.writer(output, delimiter=';', lineterminator='\n')
    writer.writerow(colunas)
    writer.writerows(csv_rows)
    
    csv_data = output.getvalue().encode('utf-8-sig')
    output.close()

    headers = {'Content-Disposition': 'attachment; filename="relatorio_zabbix.csv"'}
    return StreamingResponse(io.BytesIO(csv_data), media_type="text/csv", headers=headers)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
