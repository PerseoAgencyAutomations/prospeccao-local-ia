"""Caminhos de falha do [P1], com o lote de eval "vet" (replay). Remonta o [P1] com modelo quebrado de propósito e volta ao normal no fim.
Uso: python3 automations/pesquisa-local/build/testar_caminhos_p1.py
 1. principal fora do ar (slug inexistente) → a reserva responde (o campo model diz quem foi) e o lote fecha igual
 2. principal e reserva fora do ar → ninguém é qualificado no escuro: quem passou na regra fica "pendente"
 3. coletor fora do ar → a execução para e o [C9] registra
 4. lote parado no meio → "retomar" termina sem duplicar e sem refazer o que já foi gravado
"""
import json, os, pathlib, subprocess, sys, time, urllib.request
RAIZ = pathlib.Path(__file__).resolve().parents[3]; AQUI = pathlib.Path(__file__).resolve().parents[1]
KEY = ''.join((RAIZ / 'secrets/n8n-local-api-key').read_text().split()); TOKEN = ''.join((RAIZ / 'secrets/pl-eval-token').read_text().split())
WF = json.loads((AQUI / 'build/ids.json').read_text())['wf_p1']; PG = str(RAIZ / 'automations/contas-a-pagar/build/pg.sh')
LT = [l for l in json.loads((AQUI / 'eval/lotes.json').read_text()) if l['id'] == 'vet'][0]
LOG = pathlib.Path.home() / '.n8n-files/contas-a-pagar/erros.log'
def api(c, m='GET'):
    return json.loads(urllib.request.urlopen(urllib.request.Request('http://localhost:5678/api/v1' + c, method=m, headers={'X-N8N-API-KEY': KEY}), timeout=60).read() or b'{}')
def sql(q): o = subprocess.run([PG, '-A', '-t', '-c', q], capture_output=True, text=True, check=True).stdout.strip(); return json.loads(o) if o else None
def montar(**env): subprocess.run([sys.executable, str(AQUI / 'build/montar_p1.py')], env={**os.environ, **env}, check=True, capture_output=True)
def dispara(extra=None):
    antes = {e['id'] for e in api(f'/executions?workflowId={WF}&limit=20')['data']}
    corpo = {'token': TOKEN, 'retrato': LT['retrato'], 'nicho': LT['nicho'], 'cidade': LT['cidade'], 'termos': LT['termos'], 'exclusoes': LT['exclusoes'], 'max': 20, **(extra or {})}
    urllib.request.urlopen(urllib.request.Request('http://localhost:5678/webhook/pl-eval', data=json.dumps(corpo).encode(), headers={'Content-Type': 'application/json'}, method='POST'), timeout=30).read()
    for _ in range(100):
        time.sleep(2); novas = [e for e in api(f'/executions?workflowId={WF}&limit=20')['data'] if e['id'] not in antes]
        if novas: return novas[-1]['id']
def fim(eid):
    for _ in range(300):
        e = api(f'/executions/{eid}')
        if e['status'] in ('success', 'error', 'crashed', 'canceled'): return e['status']
        time.sleep(2)
def ultimo_lote(): return sql("select row_to_json(l) from pl.lotes l where eval order by id desc limit 1")
def contagem(l): return sql(f"select json_object_agg(etapa, n) from (select etapa, count(*) n from pl.negocios where lote_id = {l} group by etapa) t") or {}
def modelos(l): return sql(f"select json_object_agg(coalesce(modelo,'-') || ' ok=' || ok, n) from (select modelo, ok, count(*) n from pl.chamadas where lote_id = {l} group by 1, 2) t") or {}
SO = sys.argv[1] if len(sys.argv) > 1 else '1234'
ok = []
try:
    # 1
    if '1' in SO:
        montar(P1_MODELO_PRINCIPAL='particle-ai/nao-existe:free'); st = fim(dispara()); l = ultimo_lote()['id']
        c, m = contagem(l), modelos(l)
        r1 = st == 'success' and c.get('qualificado', 0) >= 7 and not any('particle' in k for k in m)
        print('1 principal fora do ar:', st, c, m, '→', 'OK' if r1 else 'FALHOU'); ok.append(r1)
    # 2
    if '2' in SO:
        montar(P1_MODELO_PRINCIPAL='particle-ai/nao-existe:free', P1_RESERVA='google/nao-existe'); st = fim(dispara()); l = ultimo_lote()['id']
        c = contagem(l)
        r2 = st == 'success' and c.get('qualificado', 0) == 0 and c.get('pendente', 0) >= 7
        print('2 principal e reserva fora do ar:', st, c, '→', 'OK' if r2 else 'FALHOU'); ok.append(r2)
    montar()
    # 3
    if '3' in SO:
        tam = LOG.stat().st_size if LOG.exists() else 0
        subprocess.run(['systemctl', '--user', 'stop', 'coletor-maps'], check=True)
        st = fim(dispara()); time.sleep(4)
        novo = LOG.read_text()[tam:] if LOG.exists() else ''
        r3 = st == 'error' and 'Pede a varredura' in novo
        print('3 coletor fora do ar:', st, '| C9:', novo.strip()[:160], '→', 'OK' if r3 else 'FALHOU'); ok.append(r3)
        subprocess.run([str(AQUI / 'coletor/subir.sh')], check=True, capture_output=True)
    # 4: queda simulada pelo estado que ela deixa (parar a execução pela API no momento certo não é confiável: o lote todo leva 60 s)
    if '4' in SO:
        st = fim(dispara()); l = ultimo_lote()['id']
        sql(f"update pl.lotes set fechado_em = null, contagens = null where id = {l}")
        manter = sql(f"select json_agg(place_id) from (select place_id from pl.negocios where lote_id = {l} order by id limit 8) t")
        sql(f"delete from pl.chamadas where lote_id = {l} and place_id not in (select jsonb_array_elements_text('{json.dumps(manter)}'::jsonb))")
        sql(f"delete from pl.negocios where lote_id = {l} and place_id not in (select jsonb_array_elements_text('{json.dumps(manter)}'::jsonb))")
        ch_mantidos = sql(f"select count(*) from pl.chamadas where lote_id = {l}")
        st = fim(dispara({'retomar': l}))
        total = sum(contagem(l).values()); dist = sql(f"select count(distinct place_id) from pl.negocios where lote_id = {l}")
        dup_ch = sql(f"select count(*) from (select place_id, etapa from pl.chamadas where lote_id = {l} group by 1, 2 having count(*) > 1) t")
        fechado = sql(f"select to_json(fechado_em is not null) from pl.lotes where id = {l}")
        ids_mantidos = sql(f"select count(*) from pl.negocios where lote_id = {l} and place_id in (select jsonb_array_elements_text('{json.dumps(manter)}'::jsonb)) and atualizado_em = criado_em")
        r4 = st == 'success' and total == 20 and dist == 20 and fechado and dup_ch == 0 and ids_mantidos == 8
        print(f"4 retomada: 8 mantidos ({ch_mantidos} chamadas), retomou → {st}, {total} negócios, {dist} distintos, chamada repetida {dup_ch}, "
              f"os 8 intocados {ids_mantidos}/8, fechado={fechado} →", 'OK' if r4 else 'FALHOU'); ok.append(r4)
finally:
    montar(); subprocess.run([str(AQUI / 'coletor/subir.sh')], capture_output=True)
print(f'\ncaminhos de falha: {sum(ok)}/{len(ok)}')
