// Prospecção local: regra, presença, conferência dos achados, decisão e ficha. Sem IA aqui dentro:
// a IA só lê (categoria, achados, abertura) e este código confere e decide.
// Roda no Node (codigo/teste-pl.js) e é colado nos Code nodes do n8n pelo build/montar_p1.py.

const semAcento = s => String(s ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
const norm = s => semAcento(s).replace(/[^a-z0-9]+/g, ' ').trim();
const compacto = s => norm(s).replace(/ /g, '');
const num = v => (v === null || v === undefined || v === '' ? null : Number(String(v).replace(',', '.')));
const verdade = v => v === true || String(v).toLowerCase() === 'true';

const REGUA = { notaMin: 4.5, avaliacoesMin: 10 };   // régua de "alvo" da sonda de Sorocaba (frentes/sites-locais/sonda-sorocaba-2026-11-10.md)
const GENERICAS = new Set(['instalacao', 'servico', 'servicos', 'conserto', 'manutencao', 'empresa', 'loja', 'clinica', 'hospital',
  'centro', 'assistencia', 'tecnica', 'tecnico', 'para', 'com', 'residencial', 'comercial']);

/** palavras do nicho a partir dos termos de busca: "instalação de ar condicionado" → ["condicionado"] */
function palavrasNicho(termos) {
  const ps = new Set();
  for (const t of termos || []) for (const w of norm(t).split(' ')) if (w.length >= 4 && !GENERICAS.has(w)) ps.add(w);
  return [...ps];
}
const raiz = w => (w.length > 7 ? w.slice(0, -2) : w);
/** alguma palavra do texto começa pela raiz de alguma palavra da lista ("veterinari" casa "veterinária" e "veterinário") */
function temPalavra(texto, lista) {
  const t = norm(texto), ws = t.split(' ');
  return (lista || []).find(p => {
    const n = norm(p); if (!n) return false;
    if (n.includes(' ')) return (' ' + t + ' ').includes(' ' + n + ' ') || t.replace(/ /g, '').includes(n.replace(/ /g, ''));   // expressão: "pet shop" (antes nunca casava)
    const r = raiz(n); return ws.some(w => w.startsWith(r));
  }) || null;
}

/** Regra sem IA. Devolve {passa, motivo}. */
function regra(l, cfg) {
  const nota = num(l.totalScore), aval = num(l.reviewsCount);
  if (verdade(l.permanentlyClosed)) return { passa: false, motivo: 'fechado' };
  if (!l.phone) return { passa: false, motivo: 'sem telefone' };
  const ex = temPalavra(`${l.title} ${l.categoryName}`, cfg.exclusoes);
  if (ex) return { passa: false, motivo: `fora do perfil: "${ex}" no nome ou na categoria` };
  if (aval === null || aval < REGUA.avaliacoesMin) return { passa: false, motivo: `poucas avaliações (${aval ?? 0}, mínimo ${REGUA.avaliacoesMin})` };
  if (nota === null || nota < REGUA.notaMin) return { passa: false, motivo: `nota ${nota ?? '-'} (mínimo ${REGUA.notaMin})` };
  return { passa: true, motivo: null };
}
const categoriaClara = (l, cfg) => !!temPalavra(`${l.categoryName} ${l.title}`, palavrasNicho(cfg.termos));

// ---------- presença: o que o negócio tem de site, conferido pela busca e pelo próprio site
const FRACO = /instagram\.com|facebook\.com|fb\.com|linktr\.ee|linktree|beacons\.ai|wa\.me|whatsapp\.com|negocio\.site|business\.site|sites\.google\.com/i;
const SOCIAL = /instagram\.com|facebook\.com|fb\.com|linktr\.ee|tiktok\.com|youtube\.com|wa\.me|linkedin\.com|kwai/i;
// sem URL(): o Code node do n8n não tem (host vazio derrubava Instagram e site próprio no eval r1, 19/11)
const host = u => (String(u || '').match(/^[a-z]+:\/\/([^\/?#:]+)/i) || [, ''])[1].toLowerCase().replace(/^www\./, '');
const LIXO_NOME = /\b(ltda|me|eireli|epp|sa|s a|ss)\b/g;
// palavra que não identifica negócio nenhum: "sorocaba.com.br" (guia da cidade) casava com "Joaquim ... Sorocaba" (eval, 19/11)
const GENERICO_DOMINIO = ['arcondicionado', 'condicionado', 'climatizacao', 'refrigeracao', 'eletricista', 'eletrica', 'veterinaria', 'veterinario',
  'clinica', 'hospital', 'servicos', 'solucoes', 'instalacao', 'manutencao', 'guia', 'pet', 'vet', 'ar'];
const sobra = (nucleo, cidade) => [compacto(cidade || ''), ...GENERICO_DOMINIO].filter(Boolean).reduce((s, g) => s.split(g).join(''), nucleo);
/** o resultado da busca é o site do próprio negócio? Domínio e nome se contêm E o domínio tem algo além de cidade e palavra genérica */
function siteProprio(nome, url, cidade) {
  const h = host(url); if (!h || SOCIAL.test(h)) return false;
  const nucleo = h.split('.')[0].replace(/-/g, '');
  const n = compacto(norm(nome).replace(LIXO_NOME, ' '));
  return nucleo.length >= 5 && n.length >= 5 && (n.includes(nucleo) || nucleo.includes(n)) && sobra(nucleo, cidade).length >= 2;
}
const QUALIFICA = ['sem_site', 'so_rede_social', 'site_fraco', 'site_fora_do_ar', 'site_ruim'];
const ROTULO_PRESENCA = { sem_site: 'sem site', so_rede_social: 'só rede social', site_fraco: 'site fraco', site_fora_do_ar: 'site fora do ar',
  site_ruim: 'site desatualizado', site_bom: 'já tem site bom', site_fora_do_maps: 'tem site (fora do Maps)', indeterminado: 'não deu pra conferir' };

/** {tipo, fatos:[{texto, fonte}]}. Fato é dado coletado, não opinião: vai pra ficha com a fonte. */
function presenca(l, site, busca) {
  const fatos = [];
  if (!l.website) {
    if (!busca || !busca.ok) return { tipo: 'indeterminado', fatos: [{ texto: 'a busca pelo nome falhou' + (busca && busca.bloqueado ? ' (bloqueada)' : ''), fonte: 'busca' }] };
    const res = busca.resultados || [];
    const proprio = res.find(r => siteProprio(l.title, r.url, l.city || busca.cidade));
    if (proprio) return { tipo: 'site_fora_do_maps', fatos: [{ texto: `o Maps não mostra site, mas a busca acha ${host(proprio.url)}`, fonte: `busca "${busca.consulta}"` }] };
    const doNegocio = tit => temPalavra(tit, norm(l.title).split(' ').filter(w => w.length >= 4)) || compacto(tit).includes(compacto(norm(l.title).replace(LIXO_NOME, ' ')));   // "Zé Vet" só tem palavra curta
    const redes = [...new Set(res.filter(r => SOCIAL.test(host(r.url)) && doNegocio(r.titulo)).map(r => host(r.url)))];
    if (redes.length) return { tipo: 'so_rede_social', fatos: [{ texto: `sem site no Maps; a busca pelo nome acha só ${redes.join(', ')}`, fonte: `busca "${busca.consulta}"` }] };
    return { tipo: 'sem_site', fatos: [{ texto: 'sem site no Maps e a busca pelo nome não acha site próprio', fonte: `busca "${busca.consulta}"` }] };
  }
  if (FRACO.test(l.website)) return { tipo: 'site_fraco', fatos: [{ texto: `o "site" no Maps é ${host(l.website)}`, fonte: 'Maps' }] };
  if (!site || !site.ok) return { tipo: 'site_fora_do_ar', fatos: [{ texto: `o site do Maps (${host(l.website)}) não abriu` + (site && (site.status || site.erro) ? `: ${site.status || String(site.erro).slice(0, 60)}` : ''), fonte: 'site' }] };
  if (site.fraco) return { tipo: 'site_fraco', fatos: [{ texto: `o site do Maps leva pra ${host(site.url_final)}`, fonte: 'site' }] };
  const prob = [];
  if (!site.https) prob.push('sem HTTPS');
  if (site.viewport === false) prob.push('não se ajusta ao celular');
  if (site.ano_copyright && site.ano_copyright <= 2019) prob.push(`© ${site.ano_copyright}`);
  if (!prob.length) return { tipo: 'site_bom', fatos: [{ texto: `site ${host(site.url_final)} com HTTPS e versão de celular` + (site.whatsapp ? ' e WhatsApp' : ''), fonte: 'site' }] };
  return { tipo: 'site_ruim', fatos: [{ texto: `site ${host(site.url_final)}: ${prob.join(', ')}`, fonte: 'site' }] };
}

// ---------- leitura da IA
function json(texto) {
  try { const m = String(texto || '').match(/\{[\s\S]*\}/); return m ? JSON.parse(m[0]) : null; } catch (e) { return null; }
}
/** a resposta do OpenRouter (corpo inteiro) → {texto, modelo, custo, tokens_in, tokens_out, erro} */
function chamada(resp, etapa) {
  const r = resp || {};
  const erro = r.error ? String(r.error.message || r.error).slice(0, 200) : null;
  return { etapa, texto: r.choices && r.choices[0] && r.choices[0].message ? String(r.choices[0].message.content || '') : '',
           modelo: r.model || null, ok: !erro && !!(r.choices && r.choices.length), custo: (r.usage && Number(r.usage.cost)) || 0,
           tokens_in: r.usage ? r.usage.prompt_tokens : null, tokens_out: r.usage ? r.usage.completion_tokens : null, erro };
}

// o trecho tem que estar na fonte, começando e terminando em fronteira de palavra (lição do business-case: "5 pedidos" ≠ "15 pedidos")
function trechoNaFonte(trecho, fonte) {
  const t = norm(trecho), f = ' ' + norm(fonte) + ' ';
  return t.replace(/ /g, '').length >= 8 && f.includes(' ' + t + ' ');
}
// frase de instrução, não palavra solta: "sistema de ar-condicionado" e "competente e qualificado" são avaliação de verdade (eval r2, 19/11)
const INSTRUCAO = /\b(ignor[ae]\w*|instruc\w*|prompt|assistente|system|marque (este|esse|como|o negocio)|classifique|responda (so|apenas|com))\b/;

/** categoria ambígua: {no_nicho: sim|nao|duvida, trecho}. "sim" só com trecho que está no nome ou na categoria. */
function leCategoria(texto, l) {
  const o = json(texto);
  if (!o || !['sim', 'nao', 'duvida'].includes(semAcento(o.no_nicho))) return { no_nicho: 'duvida', trecho: null, erro: 'formato' };
  const v = semAcento(o.no_nicho), trecho = String(o.trecho || '');
  if (v === 'sim' && !trechoNaFonte(trecho, `${l.title} ${l.categoryName}`)) return { no_nicho: 'duvida', trecho, erro: 'trecho_fora_da_fonte' };
  return { no_nicho: v, trecho, erro: null };
}

const TIPOS = ['servico', 'elogio', 'reclamacao_contato', 'reclamacao_preco', 'demanda', 'diferencial'];
/** formato mínimo pra não chamar a reserva: objeto com lista "achados" */
const achadosUteis = texto => { const o = json(texto); return !!o && Array.isArray(o.achados); };

/** achados da IA → conferidos (trecho literal na fonte certa) e descartados (com o porquê). Máx. 5. */
function leAchados(texto, fontes) {
  const o = json(texto);
  if (!o || !Array.isArray(o.achados)) return { achados: [], descartados: [], fora_do_nicho: null, erro: 'formato' };
  const achados = [], descartados = [];
  const textoFonte = f => (f === 'site' ? fontes.site || '' : (fontes.avaliacoes || []).join('\n'));
  for (const a of o.achados.slice(0, 8)) {
    const tipo = semAcento(a && a.tipo), fonte = semAcento(a && a.fonte).startsWith('site') ? 'site' : 'avaliacao';
    const item = { tipo, texto: String((a && a.texto) || '').slice(0, 160), trecho: String((a && a.trecho) || '').slice(0, 300), fonte };
    const noTrecho = new Set(item.trecho.match(/\d+/g) || []);
    const digitos = (item.texto.match(/\d+/g) || []).filter(d => !noTrecho.has(d));   // número inteiro: "5" não vale por estar dentro de "15"
    const porque = !TIPOS.includes(tipo) ? 'tipo fora da lista' : !item.texto ? 'sem texto'
      : !trechoNaFonte(item.trecho, textoFonte(fonte)) ? 'trecho não está na fonte'
      : INSTRUCAO.test(norm(item.trecho)) ? 'trecho parece instrução, não fato'
      : digitos.length ? 'número no texto que o trecho não tem' : null;
    if (porque) descartados.push({ ...item, porque }); else if (achados.length < 5) achados.push(item);
  }
  let fora = null;
  if (o.fora_do_nicho && verdade(o.fora_do_nicho.sim)) {
    const tr = String(o.fora_do_nicho.trecho || '');
    if (trechoNaFonte(tr, textoFonte('site') + '\n' + textoFonte('avaliacao')) && !INSTRUCAO.test(norm(tr))) fora = tr;
    else descartados.push({ tipo: 'fora_do_nicho', texto: 'fora do nicho', trecho: tr, fonte: '?', porque: 'trecho não está na fonte' });
  }
  return { achados, descartados, fora_do_nicho: fora, erro: null };
}

/** decisão final, sem IA */
function decide(n) {
  if (!n.regra.passa) return { etapa: 'recusado', motivo: n.regra.motivo };
  if (n.categoria && n.categoria.no_nicho !== 'sim')
    return { etapa: 'recusado', motivo: n.categoria.no_nicho === 'nao' ? 'fora do nicho (IA, com trecho)' : 'categoria incerta: a IA não confirmou com trecho' };
  const p = n.presenca;
  if (p.tipo === 'indeterminado') return { etapa: 'recusado', motivo: 'sem evidência: ' + p.fatos[0].texto };
  if (!QUALIFICA.includes(p.tipo)) return { etapa: 'recusado', motivo: ROTULO_PRESENCA[p.tipo] };
  if (!n.leitura && n.semAvaliacoes && !n.textoSite) return { etapa: 'recusado', motivo: 'sem evidência: avaliações e site não abriram' };
  if (!n.leitura) return { etapa: 'pendente', motivo: 'leitura não rodou' };
  if (n.leitura.erro) return { etapa: 'pendente', motivo: 'as duas IAs falharam ou devolveram formato errado' };
  if (n.leitura.fora_do_nicho) return { etapa: 'recusado', motivo: `as avaliações indicam outro nicho: "${n.leitura.fora_do_nicho.slice(0, 80)}"` };
  if (!n.leitura.achados.length)
    return { etapa: 'recusado', motivo: n.semAvaliacoes && !n.textoSite ? 'sem evidência: avaliações e site não abriram' : 'sem evidência: nenhum achado conferido' };
  return { etapa: 'qualificado', motivo: null };
}

// ---------- abertura por marcadores (a IA não escreve número) e ficha
const EXTENSO = /\b(zero|dois|duas|tres|quatro|cinco|seis|sete|oito|nove|dez|onze|doze|treze|catorze|quatorze|quinze|dezesseis|dezessete|dezoito|dezenove|vinte|trinta|quarenta|cinquenta|sessenta|setenta|oitenta|noventa|cem|cento|duzent\w*|trezent\w*|quatrocent\w*|quinhent\w*|seiscent\w*|setecent\w*|oitocent\w*|novecent\w*|mil|milh\w*|centena\w*|dezena\w*|duzia\w*|metade|dobro)\b/;
// frase pronta pro {presenca}: o fato cru ("sem site no Maps; a busca acha só...") ficava sem jeito na abertura (eval r2)
const FRASE_PRESENCA = { sem_site: 'não achei um site de vocês', so_rede_social: 'só achei vocês nas redes sociais',
  site_fraco: 'o link do perfil de vocês no Google leva pra uma rede social, não pra um site', site_fora_do_ar: 'o site do perfil de vocês no Google não está abrindo',
  site_ruim: 'o site de vocês parece desatualizado' };
const br1 = v => String(v).replace('.', ',');
// ordem de leitura pro vendedor: o que serve de gancho primeiro, reclamação de preço no fim (é alerta, não argumento).
// Só apresentação: a decisão não depende da ordem. Print do HubSpot (19/11): {achado_1} era "serviço", a abertura saía robótica
const ORDEM_ACHADO = { elogio: 0, diferencial: 1, demanda: 2, reclamacao_contato: 3, servico: 4, reclamacao_preco: 5 };
const ordenaAchados = as => [...(as || [])].map((a, i) => [a, i]).sort((x, y) => ((ORDEM_ACHADO[x[0].tipo] ?? 4) - (ORDEM_ACHADO[y[0].tipo] ?? 4)) || x[1] - y[1]).map(x => x[0]);
const maiuscula = t => String(t).charAt(0).toUpperCase() + String(t).slice(1);
// link curto do Maps pelo place_id (a URL da varredura ocupava 3 linhas na tarefa)
const linkMaps = l => /^ChIJ/.test(l.placeId || '') ? `https://www.google.com/maps/place/?q=place_id:${l.placeId}` : l.url;
function fatos(n, cfg) {
  const m = { nome: n.l.title, cidade: n.l.city || cfg.cidade, nicho: cfg.nicho, avaliacoes: `${num(n.l.reviewsCount)} avaliações`,
              nota: `nota ${br1(num(n.l.totalScore).toFixed(1))}`, presenca: FRASE_PRESENCA[n.presenca.tipo] || '' };
  // achado em minúscula pra caber no meio da frase ("um cliente comentou que equipe pontual...")
  // reclamação de preço não vira marcador: abrir ligação com ela queima o contato
  ordenaAchados(n.leitura.achados).filter(a => a.tipo !== 'reclamacao_preco').slice(0, 3).forEach((a, i) => { m['achado_' + (i + 1)] = a.texto.charAt(0).toLowerCase() + a.texto.slice(1).replace(/\.$/, ''); });
  const texto = 'Marcadores disponíveis (use só estes, entre chaves; o valor ao lado é só pra você entender):\n' +
    Object.entries(m).map(([k, v]) => `{${k}} = ${v}`).join('\n');
  return { texto, marcadores: m };
}
function preparaAbertura(textoIa, f) {
  const bruto = String(textoIa || '').trim().replace(/^["“]|["”]$/g, '');
  if (!bruto) return { ok: false, motivo: 'sem_texto', intrusos: [], texto: '' };
  const usados = [...bruto.matchAll(/\{([a-z_0-9]+)\}/g)].map(x => x[1]);
  const desconhecidos = usados.filter(u => !(u in f.marcadores));
  const fora = semAcento(bruto.replace(/\{[a-z_0-9]+\}/g, ' '));
  const algarismos = fora.match(/\d+/g) || [], extenso = (fora.match(EXTENSO) || [])[0];
  const [motivo, intrusos] = desconhecidos.length ? ['marcador_desconhecido', desconhecidos] : algarismos.length ? ['numero_fora_do_marcador', algarismos]
    : extenso ? ['numero_por_extenso', [extenso]] : bruto.length > 600 ? ['longo_demais', []] : [null, []];
  if (motivo) return { ok: false, motivo, intrusos, texto: '' };
  return { ok: true, motivo: null, intrusos: [], texto: bruto.replace(/\{([a-z_0-9]+)\}/g, (_, k) => f.marcadores[k]) };
}

const PERGUNTAS = {
  sem_site: ['Hoje o cliente chega por onde: indicação, Google, Instagram?', 'Quando alguém procura {nicho} em {cidade} no Google, vocês aparecem?', 'Quantos orçamentos a mais por semana vocês dariam conta de atender?'],
  so_rede_social: ['O Instagram traz cliente novo ou mais quem já conhece vocês?', 'Quando alguém procura {nicho} em {cidade} no Google, vocês aparecem?', 'Quantos orçamentos a mais por semana vocês dariam conta de atender?'],
  site_fraco: ['O link do perfil no Google leva o cliente pra onde hoje?', 'Quem pede orçamento manda mensagem ou liga?', 'Quantos orçamentos a mais por semana vocês dariam conta de atender?'],
  site_fora_do_ar: ['Vocês sabiam que o site do perfil no Google não está abrindo?', 'Quem cuida do site hoje?', 'Quanto cliente chega pelo Google?'],
  site_ruim: ['Quem cuida do site hoje?', 'O site traz pedido de orçamento ou fica parado?', 'Quanto cliente chega pelo Google?'],
};
const ROTULO_TIPO = { servico: 'serviço', elogio: 'elogio', reclamacao_contato: 'reclamação de contato', reclamacao_preco: 'cuidado, reclamação de preço', demanda: 'demanda', diferencial: 'diferencial' };
function ficha(n, cfg, abertura) {
  const l = n.l, q = (PERGUNTAS[n.presenca.tipo] || PERGUNTAS.sem_site).map(p => p.replace('{nicho}', cfg.nicho).replace('{cidade}', l.city || cfg.cidade));
  return [
    `${l.title} · ${l.categoryName || '-'} · ${l.city || cfg.cidade}`,
    `Telefone: ${l.phone} · nota ${br1(num(l.totalScore).toFixed(1))} (${num(l.reviewsCount)} avaliações) · ${linkMaps(l)}`,
    `Presença: ${ROTULO_PRESENCA[n.presenca.tipo]}. ${maiuscula(n.presenca.fatos.map(f => `${f.texto} (${f.fonte})`).join('; '))}`,
    'Achados (trecho conferido na fonte):',
    ...ordenaAchados(n.leitura.achados).map(a => `- ${ROTULO_TIPO[a.tipo] || a.tipo}: ${a.texto}. "${a.trecho}" (${a.fonte === 'site' ? 'site' : 'avaliação no Maps'})`),
    abertura && abertura.ok ? `Abertura sugerida: ${abertura.texto}` : `Abertura sugerida: (${abertura && abertura.motivo === 'sem_texto' ? 'a IA não escreveu' : 'barrada pelo cinto'}; use os achados)`,
    'Perguntas:', ...q.map((p, i) => `${i + 1}. ${p}`),
  ].join('\n');
}

if (typeof module !== 'undefined') module.exports = { semAcento, norm, palavrasNicho, temPalavra, regra, categoriaClara, siteProprio, presenca, QUALIFICA,
  ROTULO_PRESENCA, json, chamada, trechoNaFonte, leCategoria, achadosUteis, leAchados, decide, fatos, preparaAbertura, ficha, TIPOS, REGUA };
