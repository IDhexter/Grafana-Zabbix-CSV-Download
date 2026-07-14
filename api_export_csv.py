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
    # 1. Busca os Hosts (Incluindo os status de disponibilidade do Agente e SNMP)
    hosts = call_zabbix_api(ZABBIX_API_URL, "host.get", {
        "output": ["hostid", "host", "name", "status", "available", "snmp_available"],
        "selectInterfaces": ["ip", "type", "port"],
        "selectHostGroups": ["name"],
        "selectParentTemplates": ["name"],
        "selectInventory": ["os"]
    })
    
    if not hosts:
        return {"erro": "Falha ao conectar na API do Zabbix ou buscar hosts"}
        
    host_ids = [h['hostid'] for h in hosts]
    
    # 2. Busca Alertas Ativos (caso precise validar indisponibilidade por trigger de ping)
    triggers_map = {}
    triggers = call_zabbix_api(ZABBIX_API_URL, "trigger.get", {
        "output": ["triggerid", "description", "priority"],
        "selectHosts": ["hostid"],
        "monitored": True,
        "only_true": True,
        "filter": {"value": 1}
    }) or []
    
    for t in triggers:
        desc = t['description']
        for h in t.get('hosts', []):
            hid = h['hostid']
            if hid not in triggers_map:
                triggers_map[hid] = []
            triggers_map[hid].append(desc)
            
    # 3. Processar Dados Simplificados (em Inglês)
    csv_rows = []
    colunas = ["Active Name", "Technical Name", "IP Address", "Communication Type", "Operating System", "Status"]
    
    for host in hosts:
        hostid = host.get('hostid', '')
        hostname = host.get('host', '')
        name = host.get('name', '')
        status_monitoramento = host.get('status', '0') # 0 = Monitored, 1 = Disabled
        
        # Sistema Operacional do inventario
        inventory = host.get('inventory')
        os_name = inventory.get('os', 'N/A') if isinstance(inventory, dict) and inventory else "N/A"
        if os_name:
            os_name = os_name.replace("\n", " ").replace("\r", " ").strip()
        else:
            os_name = "N/A"

        # IPs das interfaces
        ips = [iface.get('ip', '') for iface in host.get('interfaces', []) if iface.get('ip')]
        ip_str = ", ".join(list(set(ips))) if ips else "N/A"
        
        # Tipo de comunicação (em Inglês)
        types = []
        for iface in host.get('interfaces', []):
            iftype = iface.get('type')
            if iftype == '1': types.append("Zabbix Agent")
            elif iftype == '2': types.append("SNMP")
            elif iftype == '3': types.append("IPMI")
            elif iftype == '4': types.append("JMX")
        type_str = ", ".join(list(set(types))) if types else "API / Agentless"
        
        # Determinação de UP ou DOWN (Online/Offline no momento do report)
        if status_monitoramento == '1':
            status_atual = "Disabled"
        else:
            agent_avail = int(host.get('available', 0))
            snmp_avail = int(host.get('snmp_available', 0))
            
            # Se alguma interface configurada estiver indisponível (2 = unavailable)
            if agent_avail == 2 or snmp_avail == 2:
                status_atual = "DOWN"
            # Se pelo menos uma estiver disponível (1 = available)
            elif agent_avail == 1 or snmp_avail == 1:
                status_atual = "UP"
            # Se for API/sem interface direta (ex: VMware que é monitorado via hipervisor)
            else:
                # Fallback: verifica se há alertas de indisponibilidade ativos para o host
                alertas = triggers_map.get(hostid, [])
                is_down = any(
                    "unavailable" in a.lower() or 
                    "down" in a.lower() or 
                    "indisponivel" in a.lower() or 
                    "ping" in a.lower() for a in alertas
                )
                status_atual = "DOWN" if is_down else "UP"
        
        row_data = [name, hostname, ip_str, type_str, os_name, status_atual]
        csv_rows.append(row_data)

    # 4. Gerar o CSV em memoria com separador ';' e codificacao utf-8-sig
    output = io.StringIO()
    output.write('\ufeff')  # BOM do UTF-8 para abrir direto no Excel
    writer = csv.writer(output, delimiter=';', lineterminator='\n')
    writer.writerow(colunas)
    writer.writerows(csv_rows)
    
    csv_data = output.getvalue().encode('utf-8-sig')
    output.close()

    headers = {'Content-Disposition': 'attachment; filename="relatorio_zabbix_basico.csv"'}
    return StreamingResponse(io.BytesIO(csv_data), media_type="text/csv", headers=headers)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
