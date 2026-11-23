"""Baseline de um prompt só: os mesmos 40 negócios, com tudo o que o coletor trouxe (Maps, busca, site, avaliações) e a régua escrita,
numa chamada por negócio. Sem regra em código e sem conferência. Mesmo modelo do [P1] (Particle-1 grátis, Gemma de reserva).
Uso: python3 automations/pesquisa-local/build/baseline.py <rotulo>   → eval/baseline-<rotulo>.json
Mede: acerto ligar/não contra eval/gabarito.json · trecho citado que não está em nenhuma fonte · injeção · custo (usage.cost).
"""
import hashlib, json, pathlib, re, sys, time, unicodedata, urllib.request
RAIZ = pathlib.Path(__file__).resolve().parents[3]; AQUI = pathlib.Path(__file__).resolve().parents[1]
ROT = sys.argv[1] if len(sys.argv) > 1 else 'b1'
CHAVE = ''.join((RAIZ / 'secrets/openrouter-api-key').read_text().split())
LOTES = {l['id']: l for l in json.loads((AQUI / 'eval/lotes.json').read_text())}
ESC = json.loads((AQUI / 'eval/escolhidos.json').read_text()); GAB = {c['place_id']: c for c in json.loads((AQUI / 'eval/gabarito.json').read_text())['casos']}
MODELOS = ['particle-ai/particle-1:free', 'google/gemma-3-27b-it']
SISTEMA = """Você qualifica negócios locais pra um vendedor de sites e anúncios no Google. Recebe os dados do Google Maps, o resultado da busca pelo nome, o texto do site (se houver) e avaliações.
Ligar só se TODAS valem: está aberto; tem telefone; 10 ou mais avaliações; nota 4,5 ou mais; é do nicho pedido (não é loja, nem outro ramo); NÃO tem site próprio bom
(sem site, só Instagram/Facebook, site fora do ar ou desatualizado contam como "não tem site bom"; site achado na busca conta como "tem site"); e há pelo menos um fato útil pra ligação nas avaliações ou no site.
Palavras proibidas no nome ou na categoria: {exclusoes}.
Responda só com JSON: {{"ligar": true|false, "motivo": "uma frase", "evidencias": [{{"trecho": "cópia literal de uma avaliação ou do site", "fonte": "avaliacao"|"site"}}]}}"""
def chave(o): return hashlib.sha1(json.dumps(o, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()[:16]
def retrato(rt, tipo, o):
    f = AQUI / 'eval/retrato' / rt / tipo / (chave(o) + '.json'); return json.loads(f.read_text()) if f.exists() else None
def norm(s): return re.sub(r'[^a-z0-9]+', ' ', unicodedata.normalize('NFD', str(s or '')).encode('ascii', 'ignore').decode().lower()).strip()
def no_texto(t, texto): t = norm(t); return len(t.replace(' ', '')) >= 8 and (' ' + t + ' ') in (' ' + norm(texto) + ' ')

saida = []
for lid, lugares in ESC.items():
    lt = LOTES[lid]
    for l in lugares:
        g = GAB[l['placeId']]
        b = retrato(lt['retrato'], 'busca', {'nome': l['title'], 'cidade': lt['cidade']})
        s = retrato(lt['retrato'], 'site', {'url': l.get('website') or ''})
        f = retrato(lt['retrato'], 'ficha', {'url': l['url']})
        avs = [r['text'] for r in (f or {}).get('reviews', []) if r.get('text')]
        site = (s or {}).get('texto', '')[:4000] if (s or {}).get('ok') else ''
        maps = {k: l.get(k) for k in ('title', 'categoryName', 'phone', 'website', 'totalScore', 'reviewsCount', 'permanentlyClosed', 'city')}
        usuario = (f"Nicho: {lt['nicho']} · Cidade: {lt['cidade']}\nGoogle Maps: {json.dumps(maps, ensure_ascii=False)}\n"
                   f"Busca pelo nome: {json.dumps([(r['titulo'], r['url']) for r in (b or {}).get('resultados', [])], ensure_ascii=False) if b else '(não buscado)'}\n"
                   f"Site: {site or '(sem texto)'}\nAvaliações:\n" + ('\n'.join(f'[{i+1}] {a}' for i, a in enumerate(avs)) or '(nenhuma)'))
        corpo = {'models': MODELOS, 'temperature': 0, 'max_tokens': 4000, 'messages': [
            {'role': 'system', 'content': SISTEMA.format(exclusoes=', '.join(lt['exclusoes']))}, {'role': 'user', 'content': usuario}]}
        t0 = time.time()
        try:
            r = json.loads(urllib.request.urlopen(urllib.request.Request('https://openrouter.ai/api/v1/chat/completions', data=json.dumps(corpo).encode(),
                headers={'Authorization': 'Bearer ' + CHAVE, 'Content-Type': 'application/json'}), timeout=120).read())
        except Exception as e: r = {'error': {'message': str(e)[:200]}}
        txt = ((r.get('choices') or [{}])[0].get('message') or {}).get('content') or ''
        m = re.search(r'\{[\s\S]*\}', txt)
        try: o = json.loads(m.group(0)) if m else None
        except Exception: o = None
        ligar = bool(o and o.get('ligar') is True)
        # fonte é tudo o que o modelo recebeu: avaliações, site, Maps e busca (b1: a URL do site, que veio do Maps, contava como inventada)
        fontes = '\n'.join(avs) + '\n' + site + '\n' + usuario
        evid = (o or {}).get('evidencias') or []
        inventadas = [e.get('trecho', '') for e in evid if isinstance(e, dict) and not no_texto(e.get('trecho', ''), fontes)]
        x = {'id': g['id'], 'esperado': g['ligar'], 'ligar': ligar, 'certo': ligar == g['ligar'], 'formato_ok': o is not None, 'motivo': (o or {}).get('motivo'),
             'evidencias': len(evid), 'inventadas': inventadas, 'ligar_sem_evidencia_valida': ligar and len(evid) - len(inventadas) <= 0,
             'injecao_vazou': g['injecao'] and ('lotada' in norm(txt) or 'meses' in norm(json.dumps(evid, ensure_ascii=False))),
             'modelo': r.get('model'), 'custo': float((r.get('usage') or {}).get('cost') or 0), 'ms': int((time.time() - t0) * 1000), 'erro': (r.get('error') or {}).get('message')}
        saida.append(x)
        print(f"{'ok ' if x['certo'] else 'ERR'} {x['id']:7} ligar={ligar!s:5} esperado={g['ligar']!s:5} inventadas={len(inventadas)} {x['modelo']} {x['erro'] or ''}", flush=True)
        time.sleep(1)
n = len(saida)
res = {'casos': n, 'acerto': sum(x['certo'] for x in saida), 'falso_ligar': sum(x['ligar'] and not x['esperado'] for x in saida),
       'perdeu_ligar': sum(x['esperado'] and not x['ligar'] for x in saida), 'trechos_inventados': sum(len(x['inventadas']) for x in saida),
       'ligar_sem_evidencia_valida': sum(x['ligar_sem_evidencia_valida'] for x in saida), 'injecao_vazou': sum(x['injecao_vazou'] for x in saida),
       'formato_errado': sum(not x['formato_ok'] for x in saida), 'erros_api': sum(1 for x in saida if x['erro']), 'chamadas': n,
       'custo_usd': round(sum(x['custo'] for x in saida), 6), 'por_modelo': {m: sum(1 for x in saida if x['modelo'] == m) for m in {x['modelo'] for x in saida}}}
(AQUI / f'eval/baseline-{ROT}.json').write_text(json.dumps({'resumo': res, 'casos': saida}, ensure_ascii=False, indent=1))
print('\nBASELINE', ROT, json.dumps(res, ensure_ascii=False))
