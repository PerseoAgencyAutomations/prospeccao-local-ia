// Escolhe os 40 negócios do eval a partir das varreduras de Sorocaba (10/11) e grava o retrato da varredura.
// node automations/pesquisa-local/build/escolhe_golden.js [--ver]
const fs = require('fs'), path = require('path'), crypto = require('crypto');
const p = require('../codigo/pl.js');
const RAIZ = path.resolve(__dirname, '../../..'), AQUI = path.resolve(__dirname, '..');
const LOTES = JSON.parse(fs.readFileSync(path.join(AQUI, 'eval/lotes.json'), 'utf8'));
const h = s => crypto.createHash('sha1').update(s).digest('hex');
const out = {};
for (const lt of LOTES) {
  const todos = JSON.parse(fs.readFileSync(path.join(RAIZ, lt.varredura), 'utf8'));
  const cls = todos.map(l => {
    const r = p.regra(l, lt), site = !l.website ? 'sem' : /instagram|facebook|linktr|wa\.me|beacons|negocio\.site/i.test(l.website) ? 'fraco' : 'proprio';
    return { l, passa: r.passa, motivo: r.motivo, clara: p.categoriaClara(l, lt), site, k: h(l.placeId) };
  }).sort((a, b) => (a.k < b.k ? -1 : 1));
  const grupos = {};
  for (const c of cls) { const g = c.passa ? `passa·${c.clara ? 'clara' : 'ambigua'}·${c.site}` : 'reprova·' + c.motivo.split(/[:(\d]/)[0].trim(); (grupos[g] ||= []).push(c); }
  if (process.argv.includes('--ver')) { console.log(lt.id, todos.length); for (const [g, v] of Object.entries(grupos)) console.log('  ', g, v.length); continue; }
  // cotas: o que testa a IA e a presença pesa mais; reprovados pela regra entram poucos (a regra é testada em codigo/teste-pl.js)
  const pega = [];
  for (const [g, v] of Object.entries(grupos)) pega.push(...v.slice(0, lt.cotas[g] ?? (g.startsWith('reprova') ? 1 : 0)));
  out[lt.id] = pega.slice(0, 20).map(c => c.l);
  const chave = crypto.createHash('sha1').update(JSON.stringify({ cidade: lt.cidade, termos: lt.termos })).digest('hex').slice(0, 16);
  const f = path.join(AQUI, 'eval/retrato', lt.retrato, 'varredura', chave + '.json');
  fs.mkdirSync(path.dirname(f), { recursive: true });
  fs.writeFileSync(f, JSON.stringify({ lugares: out[lt.id] }, null, 1));
  console.log(lt.id, out[lt.id].length, 'lugares →', path.relative(RAIZ, f));
}
if (!process.argv.includes('--ver')) fs.writeFileSync(path.join(AQUI, 'eval/escolhidos.json'), JSON.stringify(out, null, 1));
