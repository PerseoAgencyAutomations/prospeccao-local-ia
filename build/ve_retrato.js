// Mostra o que foi coletado de cada negócio do eval, pra rotular à mão (e pro operador conferir).
const fs = require('fs'), path = require('path'), crypto = require('crypto'), p = require('../codigo/pl.js');
const AQUI = path.resolve(__dirname, '..'), K = o => crypto.createHash('sha1').update(JSON.stringify(o)).digest('hex').slice(0, 16);
const LOTES = JSON.parse(fs.readFileSync(path.join(AQUI, 'eval/lotes.json'))), E = JSON.parse(fs.readFileSync(path.join(AQUI, 'eval/escolhidos.json')));
const le = (rt, tipo, o) => { const f = path.join(AQUI, 'eval/retrato', rt, tipo, K(o) + '.json'); return fs.existsSync(f) ? JSON.parse(fs.readFileSync(f)) : null; };
const so = process.argv[2];
for (const lt of LOTES) E[lt.id].forEach((l, i) => {
  const id = `${lt.id}-${String(i + 1).padStart(2, '0')}`; if (so && !id.startsWith(so)) return;
  const r = p.regra(l, lt);
  console.log(`\n## ${id} ${l.title} | ${l.categoryName} | ${l.totalScore}★ ${l.reviewsCount} | site: ${l.website || '-'}`);
  if (!r.passa) return console.log('   REGRA:', r.motivo);
  const b = le(lt.retrato, 'busca', { nome: l.title, cidade: lt.cidade }), s = le(lt.retrato, 'site', { url: l.website || '' }), f = le(lt.retrato, 'ficha', { url: l.url });
  const pr = p.presenca(l, s, b);
  console.log('   clara:', p.categoriaClara(l, lt), '| presença(código):', pr.tipo, '-', pr.fatos.map(x => x.texto).join('; '));
  if (!l.website && b) b.resultados.slice(0, 5).forEach(x => console.log('     busca:', x.titulo.slice(0, 60), '|', x.url.slice(0, 70)));
  if (l.website && s) console.log('     site:', s.ok, s.status || s.erro || '', 'https', s.https, 'vp', s.viewport, '©', s.ano_copyright, s.plataforma, '|', (s.texto || '').slice(0, 160).replace(/\n/g, ' / '));
  (f ? f.reviews : []).forEach(x => console.log('     aval', x.stars + '★:', x.text.slice(0, 150).replace(/\n/g, ' ')));
});
