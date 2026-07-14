import urllib.request
import json
import os
import sys

# CONFIGURAÇÕES DO ZABBIX
TOKEN = "SEU_TOKEN_AQUI"
BASE_URL = "http://10.10.1.26"

URLS_PARA_TENTAR = [
    f"{BASE_URL}/api_jsonrpc.php",
    f"{BASE_URL}/zabbix/api_jsonrpc.php"
]

# Diretorio onde os backups serao salvos
BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zabbix_backups_10_10_1_26")
TEMPLATES_DIR = os.path.join(BACKUP_DIR, "templates")

# Garante que os diretorios existem
os.makedirs(TEMPLATES_DIR, exist_ok=True)

# ----------------- FUNÇÃO PARA COMUNICAR COM A API -----------------
def call_api(url, method, params):
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1
    }
    data = json.dumps(payload).encode('utf-8')
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {TOKEN}"
    }
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            res_json = json.loads(response.read().decode('utf-8'))
            if 'result' in res_json:
                return res_json['result']
            elif 'error' in res_json:
                print(f"[ERRO API] Metodo {method}: {res_json['error']}")
                return None
    except Exception as e:
        print(f"[FALHA REDE] Erro ao chamar {method} em {url}: {e}")
        return None

# Testa conexao e define URL ativa
url_conectada = None
for url in URLS_PARA_TENTAR:
    print(f"Testando conexao em: {url}...")
    res = call_api(url, "apiinfo.version", {})
    if res:
        url_conectada = url
        print(f"[OK] Conectado ao Zabbix versao: {res}\n")
        break

if not url_conectada:
    print("[ERRO CRITICO] Nao foi possivel se conectar ao Zabbix.")
    sys.exit(1)

# ----------------- PASSO 1: FAZER BACKUP DE TEMPLATES -----------------
print("Buscando lista de templates cadastrados...")
templates = call_api(url_conectada, "template.get", {
    "output": ["templateid", "name"]
})

if not templates:
    print("[AVISO] Nenhum template encontrado ou erro na API.")
else:
    print(f"Encontrados {len(templates)} templates. Iniciando exportacao...")
    for idx, t in enumerate(templates, start=1):
        name = t['name']
        tid = t['templateid']
        
        # Caracteres invalidos em nomes de arquivos no Windows
        safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '_', '-')).strip()
        safe_name = safe_name.replace(' ', '_')
        filename = os.path.join(TEMPLATES_DIR, f"{safe_name}.yaml")
        
        print(f"[{idx}/{len(templates)}] Exportando: {name}...")
        
        # Exporta o template em formato YAML
        export_data = call_api(url_conectada, "configuration.export", {
            "options": {
                "templates": [tid]
            },
            "format": "yaml"
        })
        
        if export_data:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(export_data)
            except Exception as e:
                print(f"  [ERRO] Falha ao salvar arquivo {filename}: {e}")
        else:
            print(f"  [ERRO] Falha ao exportar template {name}")

print(f"\n[SUCESSO] Backup de configuracoes concluido!")
print(f"--> Os templates foram salvos em: {TEMPLATES_DIR}")
