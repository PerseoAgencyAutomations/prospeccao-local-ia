"""Monta o [P2] Aprovação e CRM e o [P3] Limpeza do eval no n8n local.
Uso: python3 automations/pesquisa-local/build/montar_p2.py   → cria/atualiza, ativa e salva workflows/p2.json e p3.json
Aprovação: http://localhost:5678/form/aprovar-leads · limpeza: POST /webhook/pl-limpa {token, lote?}
HubSpot: credencial "HubSpot Service Key account" (chave de serviço, criada pelo operador em 19/11; a chave fica só no n8n).
"""
import json, pathlib, uuid, urllib.request, urllib.error
RAIZ = pathlib.Path(__file__).resolve().parents[3]; AQUI = pathlib.Path(__file__).resolve().parents[1]
API = 'http://localhost:5678/api/v1'; KEY = ''.join((RAIZ / 'secrets/n8n-local-api-key').read_text().split())
TOKEN = ''.join((RAIZ / 'secrets/pl-eval-token').read_text().split())
IDS = json.loads((RAIZ / 'automations/contas-a-pagar/build/ids.json').read_text())
CRED_PG = {'postgres': {'id': IDS['cred_postgres'], 'name': 'Postgres contas a pagar'}}
CRED_HS = {'hubspotAppToken': {'id': 'YOUR_HUBSPOTAPPTOKEN_CREDENTIAL_ID', 'name': 'HubSpot Service Key account'}}

def req(m, c, corpo=None):
    r = urllib.request.Request(API + c, method=m, data=None if corpo is None else json.dumps(corpo).encode(),
        headers={'X-N8N-API-KEY': KEY, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(r, timeout=90) as x: t = x.read().decode(); return json.loads(t) if t else {}
    except urllib.error.HTTPError as e: raise SystemExit(f'{m} {c} -> {e.code} {e.read().decode()[:600]}')
def fab(NOME):
    def no(nome, tipo, versao, pos, params, **extra):
        return {'id': str(uuid.uuid5(uuid.NAMESPACE_URL, NOME + nome)), 'name': nome, 'type': tipo, 'typeVersion': versao,
                'position': pos, 'parameters': params, **extra}
    def code(nome, pos, corpo, por_item=True):
        return no(nome, 'n8n-nodes-base.code', 2, pos, {'mode': 'runOnceForEachItem' if por_item else 'runOnceForAllItems', 'jsCode': corpo})
    def se(nome, pos, campo):
        return no(nome, 'n8n-nodes-base.if', 2.3, pos, {
            'conditions': {'options': {'caseSensitive': True, 'leftValue': '', 'typeValidation': 'loose', 'version': 2},
                           'conditions': [{'id': str(uuid.uuid5(uuid.NAMESPACE_URL, NOME + nome)), 'leftValue': '={{ !!$json.%s }}' % campo, 'rightValue': '',
                                           'operator': {'type': 'boolean', 'operation': 'true', 'singleValue': True}}], 'combinator': 'and'}, 'options': {}})
    def pg(nome, pos, sql, valor, **extra):
        return no(nome, 'n8n-nodes-base.postgres', 2.7, pos, {'operation': 'executeQuery', 'query': sql,
                  'options': {'queryReplacement': '={{ [ %s ] }}' % valor}}, credentials=CRED_PG, **extra)
    return no, code, se, pg
def ligar(ligas):
    con = {}
    for a, b, i in ligas:
        s_ = con.setdefault(a, {}).setdefault('main', [])
        while len(s_) <= i: s_.append([])
        s_[i].append({'node': b, 'type': 'main', 'index': 0})
    return con
def publicar(NOME, nodes, ligas, arquivo):
    wf = {'name': NOME, 'nodes': nodes, 'connections': ligar(ligas),
          'settings': {'executionOrder': 'v1', 'saveDataSuccessExecution': 'all', 'saveDataErrorExecution': 'all', 'saveManualExecutions': True,
                       'errorWorkflow': IDS['wf_c9']}}
    existe = [w for w in req('GET', '/workflows?limit=100')['data'] if w['name'] == NOME]
    if existe:
        wid = existe[0]['id']
        if existe[0]['active']: req('POST', f'/workflows/{wid}/deactivate')
        req('PUT', f'/workflows/{wid}', wf)
    else:
        wid = req('POST', '/workflows', wf)['id']
    req('POST', f'/workflows/{wid}/activate')
    (AQUI / 'workflows' / arquivo).write_text(json.dumps(req('GET', f'/workflows/{wid}'), ensure_ascii=False, indent=1).replace(TOKEN, '<TOKEN_DO_EVAL>'))
    return wid

# ---------------- [P2] Aprovação e CRM
NOME = '[P2] Aprovação e CRM'; no, code, se, pg = fab(NOME)
OPCOES = ['Ligar: vai pro HubSpot', 'Descartar: fora do perfil', 'Descartar: já é cliente ou já falei', 'Descartar: dado errado']
p2 = [
  no('Aprovar lote', 'n8n-nodes-base.formTrigger', 2.6, [0, 300], {
      'formTitle': 'Aprovar leads da prospecção', 'formDescription': 'Digite o número do lote. Você vê a ficha de cada negócio qualificado e decide: ligar (vai pro HubSpot) ou descartar.',
      'formFields': {'values': [{'fieldLabel': 'Lote nº', 'fieldName': 'lote', 'fieldType': 'number', 'requiredField': True}]},
      'options': {'path': 'aprovar-leads', 'appendAttribution': False, 'buttonLabel': 'Ver os leads'}}, webhookId='p2p2p2p2-0a9a-4c0a-9b7e-b0a7a5a9a6b1'),
  pg('Qualificados do lote', [220, 300],
     "select $1::int as lote, coalesce((select json_agg(n order by n.avaliacoes desc nulls last) from pl.negocios n where n.lote_id = $1::int and n.etapa = 'qualificado'), '[]') as lista",
     "Number($json.lote ?? $json['Lote nº'])"),
  code('Monta a página', [440, 300],
     "const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');\n"
     "const lista = $json.lista || [], campos = [];\n"
     "if (!lista.length) campos.push({ fieldType: 'html', html: '<p>Nada pra aprovar nesse lote: nenhum qualificado, ou já foram aprovados.</p>' });\n"
     "for (const n of lista) {\n"
     "  campos.push({ fieldType: 'html', html: '<hr><p>' + esc(n.ficha).replace(/\\n/g, '<br>') + '</p>' });\n"
     "  campos.push({ fieldName: 'n_' + n.id, fieldLabel: 'Decisão: ' + n.nome, fieldType: 'dropdown', requiredField: true,\n"
     "                fieldOptions: { values: %s.map(o => ({ option: o })) }, defaultValue: %s });\n"
     "}\n"
     "return { json: { lote: $json.lote, lista, campos: JSON.stringify(campos), titulo: 'Lote ' + $json.lote + ': ' + lista.length + ' qualificados' } };\n"
     % (json.dumps(OPCOES, ensure_ascii=False), json.dumps(OPCOES[0], ensure_ascii=False))),
  no('Aprovação', 'n8n-nodes-base.form', 2.5, [660, 300], {'operation': 'page', 'defineForm': 'json', 'jsonOutput': '={{ $json.campos }}',
      'options': {'formTitle': '={{ $json.titulo }}', 'formDescription': 'Cada ficha traz o achado e o trecho de onde ele saiu. Nada vai pro CRM sem a sua decisão.', 'buttonLabel': 'Confirmar'}}),
  code('Separa a decisão', [880, 300],
     "const p = $('Monta a página').first().json, r = $input.first().json, decisoes = [], aprovados = [];\n"
     "for (const n of p.lista) {\n"
     "  const v = String(r['n_' + n.id] ?? r['Decisão: ' + n.nome] ?? '');\n"
     "  if (!v) continue;\n"
     "  const ligar = v.startsWith('Ligar');\n"
     "  decisoes.push({ id: n.id, etapa: ligar ? 'aprovado' : 'descartado', motivo: ligar ? null : v.replace(/^Descartar: /, '') });\n"
     "  if (ligar) aprovados.push(n);\n"
     "}\n"
     "return [{ json: { lote: p.lote, decisoes, aprovados, n_aprovados: aprovados.length, n_descartados: decisoes.length - aprovados.length } }];\n", por_item=False),
  pg('Marca as decisões', [1100, 300],
     "with u as (update pl.negocios n set etapa = d.etapa, motivo_humano = d.motivo, atualizado_em = now() from jsonb_to_recordset($1::jsonb) as d(id int, etapa text, motivo text) "
     "where n.id = d.id and n.etapa = 'qualificado' returning 1) select count(*)::int as marcados from u", 'JSON.stringify($json.decisoes)'),
  code('Só aprovados', [1320, 200],
     "const host = u => (String(u || '').match(/^[a-z]+:\\/\\/([^\\/?#:]+)/i) || [, ''])[1].toLowerCase().replace(/^www\\./, '');   // sem URL() no Code node\n"
     "return $('Separa a decisão').first().json.aprovados.map(neg => {\n"
     "  const proprio = neg.site && ['site_ruim', 'site_fora_do_ar'].includes((neg.presenca || {}).tipo);\n"
     "  return { json: { neg, dominio: proprio ? host(neg.site) : '', tem_dominio: !!proprio } };\n"
     "});\n", por_item=False),
  se('Tem domínio?', [1540, 200], 'tem_dominio'),
  no('Procura pelo domínio', 'n8n-nodes-base.hubspot', 2.2, [1760, 100], {'authentication': 'appToken', 'resource': 'company', 'operation': 'searchByDomain',
      'domain': '={{ $json.dominio }}', 'options': {}}, credentials=CRED_HS, alwaysOutputData=True),
  code('Já existe?', [1980, 100],
     "const neg = $('Só aprovados').item.json.neg, id = $json.companyId ?? null;\n"
     "return { json: { neg, companyId: id, existe: !!id } };\n"),
  se('Achou no CRM?', [2200, 100], 'existe'),
  no('Cria empresa', 'n8n-nodes-base.hubspot', 2.2, [2420, 300], {'authentication': 'appToken', 'resource': 'company', 'operation': 'create',
      'name': '={{ $json.neg.nome }}',
      'additionalFields': {'phoneNumber': '={{ $json.neg.telefone || "" }}', 'city': '={{ $json.neg.cidade || "" }}', 'websiteUrl': "={{ ['site_ruim', 'site_fora_do_ar'].includes(($json.neg.presenca || {}).tipo) ? $json.neg.site : '' }}",   # Instagram no campo site fazia a HubSpot tratar a empresa como instagram.com (print 19/11)
                           'description': "={{ 'prospeccao-n8n · lote ' + $json.neg.lote_id + ' · ' + (($json.neg.presenca || {}).tipo || '') + ' · nota ' + $json.neg.nota + ' (' + $json.neg.avaliacoes + ' avaliações)' + ($json.neg.site && !['site_ruim', 'site_fora_do_ar'].includes(($json.neg.presenca || {}).tipo) ? ' · link no Maps: ' + $json.neg.site : '') }}"}},
     credentials=CRED_HS),
  code('Junta o id', [2640, 200],
     "const neg = $json.neg ?? $('Só aprovados').item.json.neg;\n"
     "const companyId = $json.companyId;\n"
     "if (!companyId) throw new Error('HubSpot não devolveu o id da empresa de ' + neg.nome);\n"
     "const corpo = String(neg.ficha || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/\\n/g, '<br>');\n"
     "return { json: { neg, companyId: String(companyId), corpo } };\n"),
  no('Cria tarefa "Ligar"', 'n8n-nodes-base.hubspot', 2.2, [2860, 200], {'authentication': 'appToken', 'resource': 'engagement', 'operation': 'create', 'type': 'task', 'dueDate': '={{ $now.plus({ days: 1 }).toISO() }}',
      'metadata': {'subject': "={{ 'Ligar: ' + $json.neg.nome }}", 'body': '={{ $json.corpo }}', 'status': 'NOT_STARTED'},
      'additionalFields': {'associations': {'companyIds': '={{ $json.companyId }}'}}}, credentials=CRED_HS, onError='continueRegularOutput'),
  code('Resultado', [3080, 200],
     "const j = $('Junta o id').item.json, erro = $json.error ? String($json.error.message || $json.error).slice(0, 200) : null;\n"
     "return { json: { id: j.neg.id, hubspot_id: j.companyId, tarefa: erro ? null : String(($json.engagement || {}).id || ''), erro } };\n"),
  pg('Marca no CRM', [3300, 200],
     "update pl.negocios set etapa = case when ($1::jsonb->>'erro') is null then 'no_crm' else 'aprovado' end, hubspot_id = $1::jsonb->>'hubspot_id', "
     "motivo_humano = coalesce('tarefa não criada: ' || ($1::jsonb->>'erro'), motivo_humano), atualizado_em = now() where id = ($1::jsonb->>'id')::int returning id, etapa, hubspot_id",
     'JSON.stringify($json)'),
  no('Resumo', 'n8n-nodes-base.form', 2.5, [1320, 480], {'operation': 'completion', 'respondWith': 'showText',
      'responseText': "={{ '<p>Lote ' + $('Separa a decisão').first().json.lote + ': ' + $('Separa a decisão').first().json.n_aprovados + ' aprovados (empresa + tarefa \"Ligar\" no HubSpot) e ' + $('Separa a decisão').first().json.n_descartados + ' descartados.</p>' }}",
      'options': {}}),
]
c = lambda a, b, i=0: (a, b, i)
p2_ligas = [c('Aprovar lote', 'Qualificados do lote'), c('Qualificados do lote', 'Monta a página'), c('Monta a página', 'Aprovação'),
  c('Aprovação', 'Separa a decisão'), c('Separa a decisão', 'Marca as decisões'), c('Marca as decisões', 'Só aprovados'), c('Marca as decisões', 'Resumo'),
  c('Só aprovados', 'Tem domínio?'), c('Tem domínio?', 'Procura pelo domínio', 0), c('Tem domínio?', 'Cria empresa', 1),
  c('Procura pelo domínio', 'Já existe?'), c('Já existe?', 'Achou no CRM?'), c('Achou no CRM?', 'Junta o id', 0), c('Achou no CRM?', 'Cria empresa', 1),
  c('Cria empresa', 'Junta o id'), c('Junta o id', 'Cria tarefa "Ligar"'), c('Cria tarefa "Ligar"', 'Resultado'), c('Resultado', 'Marca no CRM')]
wid2 = publicar(NOME, p2, p2_ligas, 'p2.json')

# ---------------- [P3] Limpeza do eval
NOME = '[P3] Limpeza do eval'; no, code, se, pg = fab(NOME)
p3 = [
  no('Limpa o eval', 'n8n-nodes-base.webhook', 2.1, [0, 300], {'httpMethod': 'POST', 'path': 'pl-limpa', 'responseMode': 'onReceived', 'options': {}},
     webhookId='p3p3p3p3-0a9a-4c0a-9b7e-b0a7a5a9a6b1'),
  code('Confere o token', [220, 300],
     "if ($json.body.token !== '%s') throw new Error('Token do eval inválido');\n"
     "return { json: { lote: Number($json.body.lote) || 0 } };\n" % TOKEN),
  pg('Empresas do eval', [440, 300],
     "select n.id, n.hubspot_id from pl.negocios n join pl.lotes l on l.id = n.lote_id where l.eval and n.hubspot_id is not null and ($1::int = 0 or l.id = $1::int)", '$json.lote'),
  no('Apaga a empresa', 'n8n-nodes-base.hubspot', 2.2, [660, 300], {'authentication': 'appToken', 'resource': 'company', 'operation': 'delete',
      'companyId': '={{ $json.hubspot_id }}'}, credentials=CRED_HS, onError='continueRegularOutput'),
  code('Junta', [880, 300],
     "const n = $('Empresas do eval').item.json; return { json: { id: n.id, ok: !$json.error, erro: $json.error ? String($json.error.message || $json.error).slice(0, 120) : null } };\n"),
  code('Junta tudo', [1100, 300],   # uma query só com a lista inteira (antes, executeOnce + $input.all() devolvia contagem errada)
     "const l = $input.all().map(i => i.json); return [{ json: { lista: JSON.stringify(l), falharam: l.filter(x => !x.ok).length } }];\n", por_item=False),
  pg('Marca limpo', [1320, 300],
     "with u as (update pl.negocios n set hubspot_id = null, motivo_humano = 'apagado do HubSpot pela limpeza do eval', atualizado_em = now() "
     "from jsonb_to_recordset($1::jsonb) as d(id int, ok boolean) where n.id = d.id and d.ok returning n.id) "
     "select (select count(*) from u)::int as marcados, jsonb_array_length($1::jsonb) as recebidos, $2::int as falharam", "$json.lista, $json.falharam"),
]
p3_ligas = [c('Limpa o eval', 'Confere o token'), c('Confere o token', 'Empresas do eval'), c('Empresas do eval', 'Apaga a empresa'),
            c('Apaga a empresa', 'Junta'), c('Junta', 'Junta tudo'), c('Junta tudo', 'Marca limpo')]
wid3 = publicar(NOME, p3, p3_ligas, 'p3.json')
ids = json.loads((AQUI / 'build/ids.json').read_text()); ids.update({'wf_p2': wid2, 'wf_p3': wid3}); (AQUI / 'build/ids.json').write_text(json.dumps(ids, indent=1))
print('ok', wid2, wid3, 'http://localhost:5678/form/aprovar-leads')
