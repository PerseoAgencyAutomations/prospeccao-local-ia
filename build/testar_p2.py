"""Teste do [P2] pelo formulário: aprova os qualificados de um lote de eval como o gabarito manda (ligar → HubSpot; o resto → descarta)
e confere no banco e na execução que empresa + tarefa nasceram no HubSpot. Com --limpar, chama o [P3] e confere a limpeza.
Uso: python3 automations/pesquisa-local/build/testar_p2.py <lote_id> [--limpar]
"""
import json, pathlib, subprocess, sys, time, uuid, urllib.request
RAIZ = pathlib.Path(__file__).resolve().parents[3]; AQUI = pathlib.Path(__file__).resolve().parents[1]
KEY = ''.join((RAIZ / 'secrets/n8n-local-api-key').read_text().split()); TOKEN = ''.join((RAIZ / 'secrets/pl-eval-token').read_text().split())
IDS = json.loads((AQUI / 'build/ids.json').read_text()); GAB = {c['place_id']: c for c in json.loads((AQUI / 'eval/gabarito.json').read_text())['casos']}
LOTE = int(sys.argv[1]); PG = str(RAIZ / 'automations/contas-a-pagar/build/pg.sh')
def api(c): return json.loads(urllib.request.urlopen(urllib.request.Request('http://localhost:5678/api/v1' + c, headers={'X-N8N-API-KEY': KEY}), timeout=60).read())
def sql(q): o = subprocess.run([PG, '-A', '-t', '-c', q], capture_output=True, text=True, check=True).stdout.strip(); return json.loads(o) if o else None
def post(url, campos):
    b = uuid.uuid4().hex
    corpo = b''.join(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in campos.items()) + f'--{b}--\r\n'.encode()
    return urllib.request.urlopen(urllib.request.Request(url, data=corpo, method='POST', headers={'Content-Type': f'multipart/form-data; boundary={b}'}), timeout=60).read().decode()
def saidas(eid):
    e = api(f'/executions/{eid}?includeData=true'); rd = e['data']['resultData']['runData']
    out = {n: [i['json'] for r in runs for i in ((r.get('data') or {}).get('main') or [[]])[0] or []] for n, runs in rd.items()}
    return e, out
def espera(eid, ate):
    for _ in range(80):
        e, out = saidas(eid)
        if e['status'] in ('success', 'error', 'crashed') or (e['status'] == 'waiting' and ate in out): return e, out
        time.sleep(1.5)
    raise SystemExit('não terminou')

url = json.loads(post('http://localhost:5678/form/aprovar-leads', {'field-0': LOTE}))['formWaitingUrl']
eid = url.split('/form-waiting/')[1].split('?')[0]
e, out = espera(eid, 'Monta a página')
pag = out['Monta a página'][0]; campos = json.loads(pag['campos'])
print(f'lote {LOTE}: {len(pag["lista"])} qualificados na página (execução {eid})')
por_id = {n['id']: n for n in pag['lista']}; resp = {}
for i, f in enumerate(campos):
    if f.get('fieldType') != 'dropdown': continue
    n = por_id[int(f['fieldName'][2:])]; g = GAB.get(n['place_id'])
    resp[f'field-{i}'] = 'Ligar: vai pro HubSpot' if g and g['ligar'] else 'Descartar: fora do perfil'
post(url, resp)
time.sleep(2); e, out = espera(eid, 'Resumo')
if e['status'] == 'waiting': post(url, {}); time.sleep(3)
e, out = espera(eid, '__fim__')
print('status', e['status'], '| erro:', ((e['data']['resultData'].get('error') or {}).get('message')))
emp, tar = out.get('Cria empresa', []), out.get('Cria tarefa "Ligar"', [])
print(f'empresas criadas {len(emp)} · tarefas {sum(1 for t in tar if not t.get("error"))} · tarefas com erro {sum(1 for t in tar if t.get("error"))}')
for t in tar[:3]: print('  tarefa:', json.dumps(t, ensure_ascii=False)[:220])
neg = sql(f"select json_agg(json_build_object('nome', nome, 'etapa', etapa, 'hubspot_id', hubspot_id, 'motivo_humano', motivo_humano)) from pl.negocios where lote_id = {LOTE} and etapa in ('aprovado','descartado','no_crm')")
for n in neg or []: print(f"  {n['etapa']:10} {n['hubspot_id'] or '-':14} {n['nome'][:50]} {n['motivo_humano'] or ''}")
if '--limpar' in sys.argv:
    r = urllib.request.urlopen(urllib.request.Request('http://localhost:5678/webhook/pl-limpa', data=json.dumps({'token': TOKEN, 'lote': LOTE}).encode(),
                               headers={'Content-Type': 'application/json'}, method='POST'), timeout=120).read().decode()
    print('limpeza:', r[:200]); time.sleep(8)
    print('ainda com hubspot_id:', sql(f"select count(*) from pl.negocios where lote_id = {LOTE} and hubspot_id is not null"))
