"""Monta o [P1] Prospecção local (coleta e qualifica) no n8n local a partir de codigo/pl.js, prompts/*.md e do coletor.
Uso: python3 automations/pesquisa-local/build/montar_p1.py   → cria ou atualiza, ativa e salva workflows/p1.json (token do eval trocado)
Formulário: http://localhost:5678/form/prospeccao · eval: POST http://localhost:5678/webhook/pl-eval (token em secrets/pl-eval-token)
Precisa do coletor no ar: automations/pesquisa-local/coletor/subir.sh
"""
import json, os, pathlib, uuid, urllib.request, urllib.error
RAIZ = pathlib.Path(__file__).resolve().parents[3]; AQUI = pathlib.Path(__file__).resolve().parents[1]
API = 'http://localhost:5678/api/v1'; KEY = ''.join((RAIZ / 'secrets/n8n-local-api-key').read_text().split())
TOKEN = ''.join((RAIZ / 'secrets/pl-eval-token').read_text().split())
NOME = '[P1] Prospecção local'
IDS = json.loads((RAIZ / 'automations/contas-a-pagar/build/ids.json').read_text())
MODELO = os.environ.get('P1_MODELO_PRINCIPAL', 'particle-ai/particle-1:free')   # variável só pra testar a reserva quebrando o principal
RESERVA = os.environ.get('P1_RESERVA', 'google/gemma-3-27b-it')   # mesma reserva do contas-a-pagar e do business-case; variável só pra teste de falha
COLETOR = 'http://127.0.0.1:5681'
OR_URL = 'https://openrouter.ai/api/v1/chat/completions'
CRED_OR = {'openRouterApi': {'id': IDS['cred_openrouter'], 'name': 'OpenRouter (local)'}}
CRED_PG = {'postgres': {'id': IDS['cred_postgres'], 'name': 'Postgres contas a pagar'}}

def req(m, c, corpo=None):
    r = urllib.request.Request(API + c, method=m, data=None if corpo is None else json.dumps(corpo).encode(),
        headers={'X-N8N-API-KEY': KEY, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(r, timeout=90) as x: t = x.read().decode(); return json.loads(t) if t else {}
    except urllib.error.HTTPError as e: raise SystemExit(f'{m} {c} -> {e.code} {e.read().decode()[:600]}')
def ler(p): return (AQUI / p).read_text()
PL = ler('codigo/pl.js')
CONST = (f"const MODELO = {json.dumps(MODELO)}, RESERVA = {json.dumps(RESERVA)};\n"
         f"const P_CATEGORIA = {json.dumps(ler('prompts/categoria.md'))};\nconst P_ACHADOS = {json.dumps(ler('prompts/achados.md'))};\n"
         f"const P_ABERTURA = {json.dumps(ler('prompts/abertura.md'))};\n"
         "function pedido(modelos, sistema, usuario, teto) { return { models: modelos, temperature: 0, max_tokens: teto,\n"
         "  messages: [{ role: 'system', content: sistema }, { role: 'user', content: usuario }] }; }\n")
def no(nome, tipo, versao, pos, params, **extra):
    return {'id': str(uuid.uuid5(uuid.NAMESPACE_URL, NOME + nome)), 'name': nome, 'type': tipo, 'typeVersion': versao,
            'position': pos, 'parameters': params, **extra}
def code(nome, pos, corpo, por_item=True, com_pl=True):
    return no(nome, 'n8n-nodes-base.code', 2, pos, {'mode': 'runOnceForEachItem' if por_item else 'runOnceForAllItems',
              'jsCode': (PL + '\n' + CONST + '\n// ---- nó ----\n' if com_pl else '') + corpo})
def se(nome, pos, campo):
    return no(nome, 'n8n-nodes-base.if', 2.3, pos, {
        'conditions': {'options': {'caseSensitive': True, 'leftValue': '', 'typeValidation': 'strict', 'version': 2},
                       'conditions': [{'id': str(uuid.uuid5(uuid.NAMESPACE_URL, NOME + nome)), 'leftValue': '={{ $json.%s }}' % campo, 'rightValue': '',
                                       'operator': {'type': 'boolean', 'operation': 'true', 'singleValue': True}}], 'combinator': 'and'}, 'options': {}})
def coletor(nome, pos, rota, corpo_js):
    """HTTP pro coletor. corpo_js = objeto JS (expressão) com os campos que formam a chave do retrato; o replay vai à parte."""
    return no(nome, 'n8n-nodes-base.httpRequest', 4.4, pos, {'method': 'POST', 'url': COLETOR + rota, 'sendBody': True, 'specifyBody': 'json',
        # o replay vem do 'Prepara a coleta': depois do 1º HTTP o $json é a resposta do coletor (eval r1: JSON inválido)
        'jsonBody': "={{ JSON.stringify(Object.assign(%s, $('Prepara a coleta').item.json.n.cfg.retrato ? { replay: $('Prepara a coleta').item.json.n.cfg.retrato } : {})) }}" % corpo_js,
        'options': {'timeout': 120000}}, onError='continueRegularOutput')
def ia(nome, pos, campo_pedido):
    return no(nome, 'n8n-nodes-base.httpRequest', 4.4, pos, {'method': 'POST', 'url': OR_URL, 'authentication': 'predefinedCredentialType',
        'nodeCredentialType': 'openRouterApi', 'sendBody': True, 'specifyBody': 'json', 'jsonBody': '={{ JSON.stringify($json.%s) }}' % campo_pedido,
        'options': {'timeout': 120000}}, credentials=CRED_OR, onError='continueRegularOutput')
def pg(nome, pos, sql, valor):
    return no(nome, 'n8n-nodes-base.postgres', 2.7, pos, {'operation': 'executeQuery', 'query': sql,
              'options': {'queryReplacement': '={{ [ JSON.stringify(%s) ] }}' % valor}}, credentials=CRED_PG)

nodes = [
  no('Novo lote', 'n8n-nodes-base.formTrigger', 2.6, [0, 200], {
      'formTitle': 'Prospecção local com IA',
      'formDescription': 'Diga o nicho e a cidade. O coletor varre o Google Maps, a regra tira o óbvio, a IA lê site e avaliações citando o trecho, e o código decide. Quando terminar (uns 15 min pra 60 lugares), aprove os leads em /form/aprovar-leads.',
      'formFields': {'values': [
          {'fieldLabel': 'Nicho', 'fieldName': 'nicho', 'fieldType': 'text', 'requiredField': True, 'placeholder': 'ar-condicionado'},
          {'fieldLabel': 'Cidade', 'fieldName': 'cidade', 'fieldType': 'text', 'requiredField': True, 'placeholder': 'Sorocaba'},
          {'fieldLabel': 'Termos de busca no Maps (separe com ;)', 'fieldName': 'termos', 'fieldType': 'text', 'requiredField': True, 'placeholder': 'ar condicionado; instalação de ar condicionado'},
          {'fieldLabel': 'Palavras que tiram da lista (separe com ;)', 'fieldName': 'exclusoes', 'fieldType': 'text', 'placeholder': 'automotivo; loja'},
          {'fieldLabel': 'Máximo de lugares', 'fieldName': 'max', 'fieldType': 'number', 'placeholder': '60'},
          {'fieldLabel': 'Retomar o lote nº (opcional, depois de uma queda)', 'fieldName': 'retomar', 'fieldType': 'number'}]},
      'responseMode': 'onReceived',
      'options': {'path': 'prospeccao', 'appendAttribution': False, 'buttonLabel': 'Varrer',
                  'respondWithOptions': {'values': {'respondWith': 'text', 'formSubmittedText': 'Lote recebido. A coleta e a leitura levam uns 15 minutos pra 60 lugares. Depois, aprove os leads em http://localhost:5678/form/aprovar-leads'}}}},
     webhookId='p1p1p1p1-0a9a-4c0a-9b7e-b0a7a5a9a6b1'),
  no('Lote do eval', 'n8n-nodes-base.webhook', 2.1, [0, 420], {'httpMethod': 'POST', 'path': 'pl-eval', 'responseMode': 'onReceived', 'options': {}},
     webhookId='p1p1p1p1-0a9a-4c0a-9b7e-b0a7a5a9a6b2'),
  code('Prepara o lote', [220, 300],
     "const lista = s => Array.isArray(s) ? s.map(String) : String(s || '').split(';').map(x => x.trim()).filter(Boolean);\n"
     "let e = $json;\n"
     "if (e.body) {   // veio do webhook do eval: só com o token\n"
     "  if (e.body.token !== '%s') throw new Error('Token do eval inválido');\n"
     "  e = { ...e.body, eval: true };\n"
     "}\n"
     "const g = (k, rot) => e[k] ?? e[rot];\n"
     "const cfg = { nicho: String(g('nicho', 'Nicho') || '').trim(), cidade: String(g('cidade', 'Cidade') || '').trim(), uf: 'SP',\n"
     "  termos: lista(g('termos', 'Termos de busca no Maps (separe com ;)')), exclusoes: lista(g('exclusoes', 'Palavras que tiram da lista (separe com ;)')),\n"
     "  max: Math.min(Number(g('max', 'Máximo de lugares')) || 60, 200), retomar: g('retomar', 'Retomar o lote nº (opcional, depois de uma queda)') || '',\n"
     "  eval: !!e.eval, retrato: e.eval ? String(e.retrato || '') : '' };\n"
     "if (!cfg.nicho || !cfg.cidade || !cfg.termos.length) throw new Error('Faltou nicho, cidade ou termos');\n"
     "return { json: { cfg } };\n" % TOKEN, com_pl=False),
  pg('Abre o lote', [440, 300], 'select * from pl.abre_lote($1::jsonb)', '$json.cfg'),
  code('Junta o lote', [660, 300],
     "const cfg = { ...$('Prepara o lote').item.json.cfg, lote_id: $json.lote_id, retomado: $json.retomado };\n"
     "return { json: { cfg, feitos: $json.feitos || [], vistos: $json.vistos || [],\n"
     "  pedido: Object.assign({ cidade: cfg.cidade, termos: cfg.termos }, { uf: cfg.uf, max: cfg.max, resume_url: $execution.resumeUrl },\n"
     "                        cfg.retrato ? { replay: cfg.retrato } : {}) } };\n", com_pl=False),
  no('Pede a varredura', 'n8n-nodes-base.httpRequest', 4.4, [880, 300], {'method': 'POST', 'url': COLETOR + '/varredura', 'sendBody': True,
      'specifyBody': 'json', 'jsonBody': '={{ JSON.stringify($json.pedido) }}', 'options': {'timeout': 20000}}),
  no('Espera a coleta', 'n8n-nodes-base.wait', 1.1, [1100, 300], {'resume': 'webhook', 'httpMethod': 'POST', 'responseMode': 'onReceived',
      'limitWaitTime': True, 'limitType': 'afterTimeInterval', 'resumeAmount': 30, 'resumeUnit': 'minutes', 'options': {}},
     webhookId='p1p1p1p1-0a9a-4c0a-9b7e-b0a7a5a9a6b3'),
  code('Separa e tira repetidos', [1320, 300],
     "const j = $('Junta o lote').first().json, b = $input.first().json.body;\n"
     "if (!b) throw new Error('A coleta não voltou em 30 min (coletor fora do ar?)');\n"
     "if (b.erro && !(b.lugares || []).length) throw new Error('Coletor falhou - ' + String(b.erro).replace(/:/g, ' -'));\n"
     "const pular = new Set([...j.feitos, ...j.vistos]), vistos = new Set();\n"
     "const itens = (b.lugares || []).filter(l => l && l.placeId && !pular.has(l.placeId) && !vistos.has(l.placeId) && vistos.add(l.placeId)).slice(0, j.cfg.max);\n"
     "if (!itens.length) return [{ json: { nada: true, cfg: j.cfg } }];\n"
     "return itens.map(l => ({ json: { n: { cfg: j.cfg, l, chamadas: [], modelos: {} } } }));\n", por_item=False, com_pl=False),
  no('Tem o que fazer?', 'n8n-nodes-base.if', 2.3, [1540, 300], {
      'conditions': {'options': {'caseSensitive': True, 'leftValue': '', 'typeValidation': 'loose', 'version': 2},
                     'conditions': [{'id': 'tem', 'leftValue': '={{ !$json.nada }}', 'rightValue': '', 'operator': {'type': 'boolean', 'operation': 'true', 'singleValue': True}}],
                     'combinator': 'and'}, 'options': {}}),
  no('Um por vez', 'n8n-nodes-base.splitInBatches', 3, [1760, 300], {'batchSize': 1, 'options': {}}),
  code('Regra (sem IA)', [1980, 400],
     "const n = $json.n; n.regra = regra(n.l, n.cfg);\n"
     "const clara = n.regra.passa && categoriaClara(n.l, n.cfg);\n"
     "return { json: { n, passa: n.regra.passa, clara,\n"
     "  pedido_categoria: pedido([MODELO, RESERVA], P_CATEGORIA, `Nicho: ${n.cfg.nicho}\\nNome: ${n.l.title}\\nCategoria do Google: ${n.l.categoryName || '-'}`, 2000) } };\n"),
  se('Passa na regra?', [2200, 400], 'passa'),
  se('Categoria clara?', [2420, 300], 'clara'),
  ia('IA classifica a categoria', [2640, 560], 'pedido_categoria'),
  code('Lê a categoria', [2860, 560],
     "const n = $('Regra (sem IA)').item.json.n;\n"
     "const c = chamada($json, 'categoria'); n.chamadas.push({ ...c, texto: undefined });\n"
     "n.categoria = leCategoria(c.ok ? c.texto : '', n.l); n.modelos.categoria = c.ok ? c.modelo : 'nenhum';\n"
     "return { json: { n, no_nicho: n.categoria.no_nicho === 'sim' } };\n"),
  se('No nicho?', [3080, 560], 'no_nicho'),
  code('Prepara a coleta', [3300, 300], "return { json: { n: $json.n } };   // ponto de encontro: categoria clara ou confirmada pela IA\n", com_pl=False),
  coletor('Busca pelo nome', [3520, 300], '/busca', "{ nome: $('Prepara a coleta').item.json.n.l.title, cidade: $('Prepara a coleta').item.json.n.cfg.cidade }"),
  coletor('Abre o site', [3740, 300], '/site', "{ url: $('Prepara a coleta').item.json.n.l.website || '' }"),
  coletor('Lê as avaliações', [3960, 300], '/ficha', "{ url: $('Prepara a coleta').item.json.n.l.url }"),
  code('Junta a coleta', [4180, 300],
     "const n = $('Prepara a coleta').item.json.n;   // no loop, .item segue o pareamento do negócio da vez\n"
     "const busca = $('Busca pelo nome').item.json, site = $('Abre o site').item.json, aval = $json;\n"
     "n.presenca = presenca(n.l, site, busca.error ? { ok: false } : busca);\n"
     "const avaliacoes = (aval.reviews || []).map(r => r.text).filter(Boolean);\n"
     "n.fontes = { site: site.ok ? String(site.texto || '').slice(0, 4000) : '', avaliacoes };\n"
     "n.semAvaliacoes = !avaliacoes.length; n.textoSite = !!n.fontes.site;\n"
     "const vale = QUALIFICA.includes(n.presenca.tipo) && (avaliacoes.length > 0 || n.textoSite);\n"
     "const usuario = `Nicho: ${n.cfg.nicho}\\nNegócio: ${n.l.title} (${n.l.categoryName || '-'})\\n\\nTexto do site:\\n${n.fontes.site || '(sem site ou não abriu)'}\\n\\nAvaliações do Google Maps:\\n` +\n"
     "  (avaliacoes.length ? avaliacoes.map((a, i) => `[${i + 1}] ${a}`).join('\\n') : '(nenhuma)');\n"
     "return { json: { n, vale, pedido_achados: pedido([MODELO, RESERVA], P_ACHADOS, usuario, 4000), usuario } };\n"),
  se('Vale ler?', [4400, 300], 'vale'),
  ia('IA lê site e avaliações', [4620, 200], 'pedido_achados'),
  code('Confere os achados', [4840, 200],
     "const j = $('Junta a coleta').item.json, n = j.n;\n"
     "const c = chamada($json, 'achados'); n.chamadas.push({ ...c, texto: undefined });\n"
     "const util = c.ok && achadosUteis(c.texto);\n"
     "if (util) { n.leitura = leAchados(c.texto, n.fontes); n.modelos.achados = c.modelo; }\n"
     "return { json: { n, reserva: !util, pedido_reserva: pedido([RESERVA], P_ACHADOS, j.usuario, 4000) } };\n"),
  se('Precisa da reserva?', [5060, 200], 'reserva'),
  ia('Reserva lê', [5280, 420], 'pedido_reserva'),
  code('Confere a reserva', [5500, 420],
     "const j = $('Confere os achados').item.json, n = j.n;\n"
     "const c = chamada($json, 'achados_reserva'); n.chamadas.push({ ...c, texto: undefined });\n"
     "n.leitura = c.ok && achadosUteis(c.texto) ? leAchados(c.texto, n.fontes) : { achados: [], descartados: [], fora_do_nicho: null, erro: c.erro || 'formato' };\n"
     "n.modelos.achados = n.leitura.erro ? 'nenhum' : c.modelo;\n"
     "return { json: { n } };\n"),
  code('Decide (sem IA)', [5720, 200],
     "const n = $json.n; n.decisao = decide(n);\n"
     "const q = n.decisao.etapa === 'qualificado', f = q ? fatos(n, n.cfg) : null;\n"
     "return { json: { n, qualificado: q, fatos: f, pedido_abertura: q ? pedido([MODELO, RESERVA], P_ABERTURA, f.texto, 1500) : null } };\n"),
  se('Qualificado?', [5940, 200], 'qualificado'),
  ia('IA escreve a abertura', [6160, 100], 'pedido_abertura'),
  code('Ficha + cinto', [6380, 100],
     "const j = $('Decide (sem IA)').item.json, n = j.n;\n"
     "const c = chamada($json, 'abertura'); n.chamadas.push({ ...c, texto: undefined });\n"
     "const ab = preparaAbertura(c.ok ? c.texto : '', j.fatos); n.modelos.abertura = c.ok ? c.modelo : 'nenhum';\n"
     "n.abertura = ab; n.ficha = ficha(n, n.cfg, ab);\n"
     "return { json: { n } };\n"),
  code('Monta o registro', [6600, 400],
     "const n = $json.n; if (!n.decisao) n.decisao = decide(n);\n"
     "const l = n.l, le = n.leitura || {};\n"
     "return { json: { registro: { lote_id: n.cfg.lote_id, place_id: l.placeId, nome: l.title, categoria: l.categoryName, telefone: l.phone,\n"
     "  site: l.website, cidade: l.city || n.cfg.cidade, nota: l.totalScore == null ? null : Number(l.totalScore), avaliacoes: l.reviewsCount == null ? null : Number(l.reviewsCount),\n"
     "  url_maps: l.url, etapa: n.decisao.etapa, motivo: n.decisao.motivo, presenca: n.presenca || null, achados: le.achados || null,\n"
     "  descartados: (le.descartados || []).concat(n.categoria && n.categoria.erro ? [{ tipo: 'categoria', porque: n.categoria.erro, trecho: n.categoria.trecho }] : [])\n"
     "    .concat(n.abertura && !n.abertura.ok ? [{ tipo: 'abertura', porque: n.abertura.motivo, trecho: (n.abertura.intrusos || []).join(', ') }] : []),\n"
     "  ficha: n.ficha || null, abertura_ok: n.abertura ? n.abertura.ok : null, modelos: n.modelos, chamadas: n.chamadas } } };\n"),
  pg('Guarda negócio + custo', [6820, 400], 'select * from pl.guarda_negocio($1::jsonb)', '$json.registro'),
  code('Um só', [1980, 100], "const j = $('Junta o lote').first().json; return [{ json: { lote_id: j.cfg.lote_id } }];\n", por_item=False, com_pl=False),
  no('Fecha o lote', 'n8n-nodes-base.postgres', 2.7, [2200, 100], {'operation': 'executeQuery', 'query': 'select pl.fecha_lote($1::int) as resumo',
      'options': {'queryReplacement': '={{ [ $json.lote_id ] }}'}}, credentials=CRED_PG),
]
def ligar(ligas):
    con = {}
    for a, b, i in ligas:
        s_ = con.setdefault(a, {}).setdefault('main', [])
        while len(s_) <= i: s_.append([])
        s_[i].append({'node': b, 'type': 'main', 'index': 0})
    return con
c = lambda a, b, i=0: (a, b, i)
connections = ligar([
  c('Novo lote', 'Prepara o lote'), c('Lote do eval', 'Prepara o lote'), c('Prepara o lote', 'Abre o lote'), c('Abre o lote', 'Junta o lote'),
  c('Junta o lote', 'Pede a varredura'), c('Pede a varredura', 'Espera a coleta'), c('Espera a coleta', 'Separa e tira repetidos'),
  c('Separa e tira repetidos', 'Tem o que fazer?'), c('Tem o que fazer?', 'Um por vez', 0), c('Tem o que fazer?', 'Um só', 1),
  c('Um por vez', 'Um só', 0), c('Um por vez', 'Regra (sem IA)', 1), c('Um só', 'Fecha o lote'),
  c('Regra (sem IA)', 'Passa na regra?'), c('Passa na regra?', 'Categoria clara?', 0), c('Passa na regra?', 'Monta o registro', 1),
  c('Categoria clara?', 'Prepara a coleta', 0), c('Categoria clara?', 'IA classifica a categoria', 1),
  c('IA classifica a categoria', 'Lê a categoria'), c('Lê a categoria', 'No nicho?'), c('No nicho?', 'Prepara a coleta', 0), c('No nicho?', 'Monta o registro', 1),
  c('Prepara a coleta', 'Busca pelo nome'), c('Busca pelo nome', 'Abre o site'), c('Abre o site', 'Lê as avaliações'), c('Lê as avaliações', 'Junta a coleta'),
  c('Junta a coleta', 'Vale ler?'), c('Vale ler?', 'IA lê site e avaliações', 0), c('Vale ler?', 'Monta o registro', 1),
  c('IA lê site e avaliações', 'Confere os achados'), c('Confere os achados', 'Precisa da reserva?'),
  c('Precisa da reserva?', 'Reserva lê', 0), c('Precisa da reserva?', 'Decide (sem IA)', 1), c('Reserva lê', 'Confere a reserva'), c('Confere a reserva', 'Decide (sem IA)'),
  c('Decide (sem IA)', 'Qualificado?'), c('Qualificado?', 'IA escreve a abertura', 0), c('Qualificado?', 'Monta o registro', 1),
  c('IA escreve a abertura', 'Ficha + cinto'), c('Ficha + cinto', 'Monta o registro'),
  c('Monta o registro', 'Guarda negócio + custo'), c('Guarda negócio + custo', 'Um por vez'),
])
wf = {'name': NOME, 'nodes': nodes, 'connections': connections,
      'settings': {'executionOrder': 'v1', 'saveDataSuccessExecution': 'all', 'saveDataErrorExecution': 'all', 'saveManualExecutions': True,
                   **({'errorWorkflow': IDS['wf_c9']} if 'wf_c9' in IDS else {})}}
existe = [w for w in req('GET', '/workflows?limit=100')['data'] if w['name'] == NOME]
if existe:
    wid = existe[0]['id']
    if existe[0]['active']: req('POST', f'/workflows/{wid}/deactivate')
    req('PUT', f'/workflows/{wid}', wf)
else:
    wid = req('POST', '/workflows', wf)['id']
req('POST', f'/workflows/{wid}/activate')
(AQUI / 'workflows').mkdir(exist_ok=True)
(AQUI / 'workflows/p1.json').write_text(json.dumps(req('GET', f'/workflows/{wid}'), ensure_ascii=False, indent=1)
                                        .replace(TOKEN, '<TOKEN_DO_EVAL>').replace(str(pathlib.Path.home()), '~'))
ids = json.loads((AQUI / 'build/ids.json').read_text()) if (AQUI / 'build/ids.json').exists() else {}
ids['wf_p1'] = wid; (AQUI / 'build/ids.json').write_text(json.dumps(ids, indent=1))
print('ok', wid, 'http://localhost:5678/form/prospeccao')
