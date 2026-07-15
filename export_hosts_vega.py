import urllib.request
import json
import sys
import os
import csv

# CONFIGURAÇÕES DO SEU ZABBIX - COLOQUE O SEU TOKEN
TOKEN = "SEU_TOKEN_AQUI"
BASE_URL = "http://10.10.1.26"

URLS_PARA_TENTAR = [
    f"{BASE_URL}/api_jsonrpc.php",
    f"{BASE_URL}/zabbix/api_jsonrpc.php"
]

print("Iniciando conexao com a API do Zabbix...")

payload_hosts = {
    "jsonrpc": "2.0",
    "method": "host.get",
    "params": {
        "output": [
            "hostid", "host", "name", "status", "proxy_hostid", "description"
        ],
        "selectInterfaces": ["ip", "type", "port"],
        "selectHostGroups": ["name"],
        "selectParentTemplates": ["name"],
        "selectInventory": ["os", "hardware", "software", "serialno_a"]
    },
    "id": 1
}

data_hosts = json.dumps(payload_hosts).encode('utf-8')
headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {TOKEN}"
}

sucesso = False
hosts = None
url_conectada = ""

for url in URLS_PARA_TENTAR:
    print(f"Tentando conectar em: {url}...")
    req = urllib.request.Request(url, data=data_hosts, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            res_data = response.read().decode('utf-8')
            res_json = json.loads(res_data)
            if 'result' in res_json:
                hosts = res_json['result']
                sucesso = True
                url_conectada = url
                print(f"[OK] Conectado com sucesso em: {url}")
                break
    except Exception as e:
        print(f"[FALHA REDE] {url}: {e}")

if not sucesso:
    print("[ERRO CRITICO] Nao foi possivel conectar à API do Zabbix.")
    sys.exit(1)

host_ids = [h['hostid'] for h in hosts]

proxies_map = {}
payload_proxies = {
    "jsonrpc": "2.0",
    "method": "proxy.get",
    "params": {"output": ["proxyid", "name"]},
    "id": 2
}
try:
    data_proxies = json.dumps(payload_proxies).encode('utf-8')
    req_proxies = urllib.request.Request(url_conectada, data=data_proxies, headers=headers)
    with urllib.request.urlopen(req_proxies, timeout=10) as response:
        res_proxies = json.loads(response.read().decode('utf-8'))
        if 'result' in res_proxies:
            for p in res_proxies['result']:
                proxies_map[str(p['proxyid'])] = p['name']
except Exception as e:
    print(f"[AVISO] Falha ao listar proxies: {e}")

triggers_map = {}
payload_triggers = {
    "jsonrpc": "2.0",
    "method": "trigger.get",
    "params": {
        "output": ["triggerid", "description", "priority"],
        "selectHosts": ["hostid"],
        "monitored": True,
        "only_true": True,
        "filter": {"value": 1}
    },
    "id": 3
}
try:
    data_triggers = json.dumps(payload_triggers).encode('utf-8')
    req_triggers = urllib.request.Request(url_conectada, data=data_triggers, headers=headers)
    with urllib.request.urlopen(req_triggers, timeout=15) as response:
        res_triggers = json.loads(response.read().decode('utf-8'))
        if 'result' in res_triggers:
            priorities = {
                "0": "Classif.", "1": "Info", "2": "Atencao", 
                "3": "Media", "4": "Alta", "5": "Desastre"
            }
            for t in res_triggers['result']:
                desc = t['description']
                priority_label = priorities.get(str(t['priority']), "Info")
                for h in t.get('hosts', []):
                    hid = h['hostid']
                    if hid not in triggers_map:
                        triggers_map[hid] = []
                    triggers_map[hid].append(f"[{priority_label.upper()}] {desc}")
except Exception as e:
    print(f"[AVISO] Falha ao listar alertas ativos: {e}")

payload_items = {
    "jsonrpc": "2.0",
    "method": "item.get",
    "params": {
        "hostids": host_ids,
        "output": ["hostid", "name", "key_", "lastvalue", "units"],
        "search": {
            "key_": [
                "cpu.util", "cpu.usage", "hrProcessorLoad", 
                "memory.util", "memory.size[pused]", "memory.used", 
                "pused",
                "system.sw.os", "system.descr", "system.uname", "system.hw.os", "sysDescr",
                "system.hw.model", "system.hw.device",
                "system.uptime", "sysUpTimeInstance", "hrSystemUptime"
            ]
        },
        "searchByAny": True,
        "monitored": True
    },
    "id": 4
}
data_items = json.dumps(payload_items).encode('utf-8')
req_items = urllib.request.Request(url_conectada, data=data_items, headers=headers)

items = []
try:
    with urllib.request.urlopen(req_items, timeout=25) as response:
        res_json = json.loads(response.read().decode('utf-8'))
        if 'result' in res_json:
            items = res_json['result']
except Exception as e:
    print(f"[AVISO] Erro ao buscar itens: {e}")

host_items_map = {}
for item in items:
    hid = item['hostid']
    if hid not in host_items_map:
        host_items_map[hid] = []
    host_items_map[hid].append(item)

colunas = [
    "ID do Host", "Nome Tecnico", "Nome Visivel", "Endereco IP", 
    "Modelo de Monitoramento", "Status (Ativo/Inativo)", "Proxy de Monitoramento",
    "CPU Ult. Valor", "Memoria Ult. Valor", "Discos (Uso %)", "Uptime", "Alertas Ativos no Ativo",
    "Grupos", "Templates Vinculados", "Sistema Operacional (OS)", "Hardware", "Numero de Serie", "Descricao"
]

aba_geral = []

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
        
        if key in ["system.sw.os", "system.descr", "system.uname", "system.hw.os", "sysDescr"]:
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
    
    aba_geral.append(row_data)

csv_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ativos_zabbix_vega.csv")
try:
    with open(csv_file, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(colunas)
        writer.writerows(aba_geral)
    print(f"\n[SUCESSO] Relatorio CSV (.csv) gerado: {csv_file}")
except Exception as e:
    print(f"\n[ERRO] Falha ao salvar o arquivo CSV: {e}")
    sys.exit(1)
