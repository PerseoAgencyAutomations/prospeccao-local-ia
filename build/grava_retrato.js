// Congela busca, site e avaliações dos negócios do eval (o coletor grava em eval/retrato/<retrato>/).
// O corpo de cada pedido tem que ser IGUAL ao que o [P1] manda, senão o replay não acha: {nome, cidade} · {url} · {url}.
// node automations/pesquisa-local/build/grava_retrato.js   (com o coletor no ar)
const fs = require('fs'), path = require('path'), p = require('../codigo/pl.js');
const AQUI = path.resolve(__dirname, '..');
const LOTES = JSON.parse(fs.readFileSync(path.join(AQUI, 'eval/lotes.json'), 'utf8'));
const ESC = JSON.parse(fs.readFileSync(path.join(AQUI, 'eval/escolhidos.json'), 'utf8'));
const post = (rota, corpo) => fetch('http://127.0.0.1:5681' + rota, { method: 'POST', body: JSON.stringify(corpo) }).then(r => r.json());
(async () => {
  for (const lt of LOTES) {
    const fila = ESC[lt.id].filter(l => p.regra(l, lt).passa);
    const um = async () => {
      for (let l; (l = fila.shift()); ) {
        const [b, s, f] = await Promise.all([post('/busca', { nome: l.title, cidade: lt.cidade, gravar: lt.retrato }),
          post('/site', { url: l.website || '', gravar: lt.retrato }), post('/ficha', { url: l.url, gravar: lt.retrato })]);
        console.log(lt.id, l.title.slice(0, 40).padEnd(40), 'busca', b.ok ? b.resultados.length : 'X', '| site', l.website ? (s.ok ? 'ok' : 'X ' + (s.erro || s.status)) : '-', '| aval.', f.reviews.length);
        await new Promise(r => setTimeout(r, 1500));
      }
    };
    await Promise.all([um(), um()]);
  }
})();
