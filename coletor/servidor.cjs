#!/usr/bin/env node
/*
 * Coletor local do [P1] Prospecção local: Google Maps, site e busca pelo Chromium, sem API paga.
 * O n8n 2.x vem com o Execute Command desligado (@n8n/config nodes.config.js), por isso isto é um serviço HTTP em
 * 127.0.0.1 que o n8n chama com o HTTP Request.
 *
 *   node automations/pesquisa-local/coletor/servidor.cjs [--porta 5681]
 *
 * POST /varredura {cidade, uf, termos[], max, resume_url, replay?, gravar?}  → 202 na hora; quando termina, POST no
 *      resume_url (o Wait do n8n) com {lugares, erro}. Lugares no formato do Apify compass~crawler-google-places.
 * POST /ficha {url}            → {ok, reviews:[{text, stars}], fonte}   (até 5 avaliações, sem login)
 * POST /site {url}             → {ok, url_final, texto, https, viewport, whatsapp, ano_copyright, plataforma, erro}
 * POST /busca {nome, cidade}   → {ok, consulta, resultados:[{titulo, url}], bloqueado}
 *
 * Replay (eval): com "replay": "<retrato>" no corpo, nada sai pra internet: a resposta vem de eval/retrato/<retrato>/.
 * Com "gravar": "<retrato>", a resposta ao vivo é guardada lá. É o que deixa o eval reproduzível (o Maps muda todo dia).
 * Lógica de lista e ficha vinda de tools/sonda-maps.cjs e tools/ficha-maps.cjs (testados em Sorocaba, 10/11).
 */
const fs = require("fs");
const os = require("os");
const path = require("path");
const http = require("http");
const crypto = require("crypto");

function playwright() {
  try { return require("playwright-core"); } catch {}
  const npx = path.join(os.homedir(), ".npm/_npx");
  for (const d of fs.existsSync(npx) ? fs.readdirSync(npx) : []) {
    const p = path.join(npx, d, "node_modules/playwright-core");
    if (fs.existsSync(p)) return require(p);
  }
  throw new Error("playwright-core não encontrado. Rode uma vez: npx playwright-core --version");
}
const UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";
const arg = (n, p = null) => (process.argv.includes(n) ? process.argv[process.argv.indexOf(n) + 1] : p);
const PORTA = Number(arg("--porta", 5681));
const RETRATOS = path.resolve(__dirname, "../eval/retrato");
const espera = (ms) => new Promise((r) => setTimeout(r, ms));
const numero = (t) => Number(String(t).replace(/\./g, "").replace(",", "."));
const chave = (o) => crypto.createHash("sha1").update(JSON.stringify(o)).digest("hex").slice(0, 16);
const log = (...a) => console.error(new Date().toISOString().slice(11, 19), ...a);

let navegador = null;
async function browser() {
  if (!navegador || !navegador.isConnected()) navegador = await playwright().chromium.launch({ headless: true });
  return navegador;
}
async function contexto() { return (await browser()).newContext({ locale: "pt-BR", viewport: { width: 1280, height: 900 }, userAgent: UA }); }

// ---------- Maps: lista e ficha (de tools/sonda-maps.cjs)
async function listar(termo, cidade, uf) {
  const ctx = await contexto();
  try {
    const p = await ctx.newPage();
    await p.goto(`https://www.google.com/maps/search/${encodeURIComponent(`${termo} em ${cidade} ${uf}`)}?hl=pt-BR&gl=br`, { waitUntil: "domcontentloaded" });
    await p.waitForSelector('div[role="feed"]', { timeout: 30000 });
    await p.waitForTimeout(2000);
    for (let i = 0, antes = -1, parado = 0; i < 40 && parado < 4; i++) {
      const n = await p.locator('div[role="feed"] a[href*="/maps/place/"]').count();
      if (await p.getByText("Você chegou ao final da lista").count()) break;
      parado = n === antes ? parado + 1 : 0;
      antes = n;
      await p.evaluate(() => { const f = document.querySelector('div[role="feed"]'); f.scrollTop = f.scrollHeight; });
      await p.waitForTimeout(1500);
    }
    return await p.evaluate(() =>
      [...document.querySelectorAll('div[role="feed"] a[href*="/maps/place/"]')].map((a) => {
        const c = a.closest('div[role="article"]') || a.parentElement;
        const nota = c.querySelector('span[role="img"][aria-label*="estrela"]');
        const linhas = [...c.querySelectorAll(".W4Efsd")].map((e) => e.innerText);
        return {
          title: a.getAttribute("aria-label"), href: a.href,
          nota: nota?.getAttribute("aria-label") || null,
          contagem: nota?.innerText.match(/\(([\d.]+)\)/)?.[1] || null,
          categoria: linhas.map((l) => l.split("·")[0].trim()).find((l) => l && !/^\d/.test(l)) || null,
          telefone: c.querySelector(".UsdlK")?.innerText || null,
        };
      }));
  } finally { await ctx.close(); }
}

async function fichaBasica(url) {
  const ctx = await contexto();
  try {
    const p = await ctx.newPage();
    await p.goto(url, { waitUntil: "domcontentloaded" });
    await p.waitForSelector("h1", { timeout: 30000 });
    await p.waitForTimeout(1500);
    return await p.evaluate(() => {
      const aria = [...document.querySelectorAll("[aria-label]")].map((e) => e.getAttribute("aria-label") || "");
      const achado = (pre) => aria.find((a) => a.startsWith(pre))?.slice(pre.length).trim() || null;
      const topo = document.querySelector('div[role="main"]')?.innerText || "";
      return {
        title: document.querySelector("h1")?.innerText.trim() || null,
        categoryName: document.querySelector('button[jsaction*="category"]')?.innerText.trim() || null,
        website: document.querySelector('a[data-item-id="authority"]')?.href || null,
        address: achado("Endereço:"), phone: achado("Telefone:"),
        nota: aria.map((a) => a.match(/^([\d,]+) estrelas?\s*$/)).find(Boolean)?.[1] || null,
        contagem: aria.map((a) => a.match(/^([\d.]+) avaliaç/)).find(Boolean)?.[1] || topo.match(/\n\(([\d.]+)\)\n/)?.[1] || null,
        fechado: /Fechado permanentemente|Fechado temporariamente/.test(topo),
      };
    });
  } catch (e) { return { erro: e.message.split("\n")[0] }; } finally { await ctx.close(); }
}

function formatoApify(l, d) {
  const end = d.address || "";
  const m = end.match(/^(.*?)(?: - ([^,]+))?, ([^,]+) - ([A-Z]{2}), (\d{5}-\d{3})/);
  const hex = l.href.match(/!1s0x[0-9a-f]+:(0x[0-9a-f]+)/)?.[1];
  const contagem = d.contagem || l.contagem, tel = d.phone || l.telefone, nota = d.nota || l.nota;
  return {
    title: d.title || l.title, categoryName: d.categoryName || l.categoria, address: end || null,
    city: m ? m[3] : null, state: m ? m[4] : null,
    phone: tel ? tel.replace(/^\((\d{2})\)\s*/, "+55 $1 ") : null, website: d.website || null,
    totalScore: nota ? numero(nota.match(/[\d,]+/)[0]) : null, reviewsCount: contagem ? numero(contagem) : null,
    permanentlyClosed: !!d.fechado, url: l.href.replace(/\?.*$/, "?hl=pt-BR"), placeId: l.placeId,
    cid: hex ? BigInt(hex).toString() : null, searchString: l.searchString, scrapedAt: new Date().toISOString(),
    fonte: d.erro ? `chromium · ficha falhou: ${d.erro}` : "chromium",
  };
}

async function varredura({ cidade, uf = "SP", termos = [], max = 60 }) {
  const lugares = new Map();
  for (const termo of termos) {
    for (const c of await listar(termo, cidade, uf)) {
      const id = c.href.match(/!19s(ChIJ[^?!&]+)/)?.[1] || c.href.match(/!1s(0x[0-9a-f]+:0x[0-9a-f]+)/)?.[1] || c.title;
      if (!lugares.has(id)) lugares.set(id, { ...c, placeId: id, searchString: termo });
    }
    log(`varredura ${termo}: ${lugares.size} lugares`);
  }
  const fila = [...lugares.values()].slice(0, max), saida = [];
  const trabalhador = async () => {
    for (let l; (l = fila.shift()); ) {
      let d = await fichaBasica(l.href);
      for (let t = 1; t < 3 && !d.erro && !d.website && !d.contagem && !l.contagem; t++) { await espera(2000); const n = await fichaBasica(l.href); if (!n.erro) d = n; }
      saida.push(formatoApify(l, d));
      await espera(800);
    }
  };
  await Promise.all([trabalhador(), trabalhador(), trabalhador()]);
  return saida;
}

// ---------- avaliações (de tools/ficha-maps.cjs, sem a galeria)
async function ficha({ url }) {
  const ctx = await contexto();
  try {
    let p, t = 0;
    for (; t < 4; t++) {
      if (p) { await p.close(); await espera(3000); }
      p = await ctx.newPage();
      await p.goto(url, { waitUntil: "domcontentloaded" });
      await p.waitForSelector("h1", { timeout: 30000 });
      await p.waitForTimeout(2500);
      if (await p.getByRole("tab", { name: /^Avaliações/ }).count()) break;
    }
    if (t === 4) return { ok: false, reviews: [], fonte: "página reduzida, sem aba de avaliações" };
    await p.getByRole("tab", { name: /^Avaliações/ }).first().click();
    await p.waitForTimeout(2500);
    await p.evaluate(() => document.querySelectorAll('button[aria-label="Ver mais"]').forEach((b) => b.click()));
    await p.waitForTimeout(800);
    const reviews = await p.evaluate(() => {
      const vistos = new Set();
      return [...document.querySelectorAll("div[data-review-id][aria-label]")]
        .filter((r) => !vistos.has(r.dataset.reviewId) && vistos.add(r.dataset.reviewId))
        .map((r) => ({
          stars: Number(r.querySelector('[role="img"][aria-label*="estrela"]')?.getAttribute("aria-label")?.match(/\d/)?.[0]) || null,
          text: r.querySelector('span[class*="wiI7pd"]')?.innerText || null,
        })).filter((r) => r.text).slice(0, 5);
    });
    return { ok: true, reviews, fonte: `chromium sem login · ${t + 1} tentativa(s)` };
  } catch (e) { return { ok: false, reviews: [], fonte: "erro: " + e.message.split("\n")[0] }; } finally { await ctx.close(); }
}

// ---------- site do negócio
const FRACO = /instagram\.com|facebook\.com|fb\.com|linktr\.ee|linktree|beacons\.ai|wa\.me|whatsapp\.com|negocio\.site|business\.site|sites\.google\.com/i;
async function site({ url }) {
  if (!url) return { ok: false, erro: "sem url" };
  if (FRACO.test(url)) return { ok: true, url_final: url, fraco: true, texto: "", https: /^https:/.test(url), viewport: null, whatsapp: /wa\.me|whatsapp/i.test(url), ano_copyright: null, plataforma: url.match(FRACO)[0] };
  const ctx = await contexto();
  try {
    const p = await ctx.newPage();
    const r = await p.goto(url, { waitUntil: "domcontentloaded", timeout: 25000 });
    await p.waitForTimeout(2500);
    const d = await p.evaluate(() => {
      const html = document.documentElement.outerHTML;
      const texto = (document.body?.innerText || "").replace(/\s+\n/g, "\n").replace(/[ \t]+/g, " ").trim();
      const anos = [...texto.matchAll(/(?:©|copyright|\(c\))\s*(?:\d{4}\s*[-–]\s*)?(\d{4})/gi)].map((m) => Number(m[1]));
      const gen = document.querySelector('meta[name="generator"]')?.content || "";
      const plat = /wix\.com|wixstatic/i.test(html) ? "Wix" : /wp-content|wordpress/i.test(html) ? "WordPress" : /squarespace/i.test(html) ? "Squarespace" : gen || null;
      return { texto: texto.slice(0, 6000), viewport: !!document.querySelector('meta[name="viewport"]'),
               whatsapp: /wa\.me\/|api\.whatsapp\.com|whatsapp:\/\//i.test(html), ano_copyright: anos.length ? Math.max(...anos) : null, plataforma: plat };
    });
    const status = r ? r.status() : 0;
    return { ok: status > 0 && status < 400, status, url_final: p.url(), fraco: FRACO.test(p.url()), https: p.url().startsWith("https:"), ...d };
  } catch (e) { return { ok: false, erro: e.message.split("\n")[0].slice(0, 200) }; } finally { await ctx.close(); }
}

// ---------- busca pelo nome (confirma o "sem site": o campo do Maps erra)
async function busca({ nome, cidade }) {
  const consulta = `${nome} ${cidade}`;
  try {
    let r, h;
    for (let t = 0; t < 3; t++) {   // 202 = limite de pedidos do DuckDuckGo (visto na gravação do eval, 19/11): espera e tenta de novo
      if (t) await espera(4000 * t);
      r = await fetch("https://html.duckduckgo.com/html/?q=" + encodeURIComponent(consulta), { headers: { "User-Agent": UA, "Accept-Language": "pt-BR" } });
      h = await r.text();
      if (r.status === 200) break;
    }
    if (r.status !== 200 || /anomaly|captcha/i.test(h) && !/result__a/.test(h)) return { ok: false, consulta, resultados: [], bloqueado: true, status: r.status };
    const resultados = [...h.matchAll(/class="result__a"[^>]*href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/g)].map((m) => {
      let u = m[1].replace(/&amp;/g, "&");
      const uddg = u.match(/uddg=([^&]+)/); if (uddg) u = decodeURIComponent(uddg[1]);
      return { titulo: m[2].replace(/<[^>]+>/g, "").replace(/&amp;/g, "&").replace(/&#x27;/g, "'").trim(), url: u };
    }).filter((x) => !/duckduckgo\.com\/y\.js|ad_domain=/.test(x.url)).slice(0, 8);   // anúncio não é resultado
    return { ok: true, consulta, resultados, bloqueado: false };
  } catch (e) { return { ok: false, consulta, resultados: [], bloqueado: false, erro: e.message.slice(0, 200) }; }
}

// ---------- replay / gravação
function arquivoRetrato(retrato, tipo, entrada) {
  if (!/^[a-z0-9-]+$/.test(retrato)) throw new Error("nome de retrato inválido");
  return path.join(RETRATOS, retrato, tipo, chave(entrada) + ".json");
}
async function comRetrato(tipo, corpo, fn) {
  const { replay, gravar, resume_url, ...entrada } = corpo;
  const id = tipo === "varredura" ? { cidade: entrada.cidade, termos: entrada.termos } : entrada;
  if (replay) {
    const f = arquivoRetrato(replay, tipo, id);
    if (!fs.existsSync(f)) return tipo === "varredura" ? { lugares: [], erro: "retrato sem varredura" } : { ok: false, erro: "fora do retrato", replay: true };
    return JSON.parse(fs.readFileSync(f, "utf8"));
  }
  const r = await fn(entrada);
  if (gravar) { const f = arquivoRetrato(gravar, tipo, id); fs.mkdirSync(path.dirname(f), { recursive: true }); fs.writeFileSync(f, JSON.stringify(r, null, 1)); }
  return r;
}

// o Chromium aberto segurava o processo e o systemd levava 90 s pra matar (visto em 19/11)
for (const s of ["SIGTERM", "SIGINT"]) process.on(s, async () => { try { if (navegador) await navegador.close(); } catch {} process.exit(0); });

// ---------- HTTP
const ROTAS = { "/ficha": ficha, "/site": site, "/busca": busca };
http.createServer((req, res) => {
  let corpo = "";
  req.on("data", (c) => { corpo += c; if (corpo.length > 1e6) req.destroy(); });
  req.on("end", async () => {
    const responde = (s, o) => { res.writeHead(s, { "Content-Type": "application/json" }); res.end(JSON.stringify(o)); };
    if (req.method === "GET" && req.url === "/saude") return responde(200, { ok: true });
    if (req.method !== "POST") return responde(405, { erro: "use POST" });
    let e; try { e = JSON.parse(corpo || "{}"); } catch { return responde(400, { erro: "JSON inválido" }); }
    try {
      if (req.url === "/varredura") {
        if (!e.resume_url || !/^http:\/\/(localhost|127\.0\.0\.1):5678\//.test(e.resume_url)) return responde(400, { erro: "resume_url do n8n local obrigatório" });
        responde(202, { aceito: true });
        let r;
        try { r = await comRetrato("varredura", { ...e, max: Math.min(Number(e.max) || 60, 200) }, async (x) => ({ lugares: await varredura(x) })); }
        catch (err) { r = { lugares: [], erro: err.message.slice(0, 300) }; }
        if (e.max) r = { ...r, lugares: (r.lugares || []).slice(0, Number(e.max)) };
        log(`varredura pronta: ${(r.lugares || []).length} lugares${r.erro ? " · " + r.erro : ""}`);
        // em replay a resposta sai em 1 s, antes de a execução chegar no Wait: o n8n recusa e a execução ficava parada (eval r1, 19/11).
        // Tenta de novo até o n8n aceitar.
        for (let t = 0; t < 40; t++) {
          await espera(t ? 3000 : 1500);
          const st = await fetch(e.resume_url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(r) })
            .then((x) => x.status).catch((x) => "erro " + x.message);
          if (st === 200) { log(`n8n acordado (tentativa ${t + 1})`); return; }
          if (t === 0 || t % 10 === 9) log(`resume ainda não aceito: ${st}`);
        }
        log("resume desistiu depois de 40 tentativas: o Wait do n8n vence em 30 min e o erro vai pro [C9]");
        return;
      }
      const fn = ROTAS[req.url];
      if (!fn) return responde(404, { erro: "rota desconhecida" });
      responde(200, await comRetrato(req.url.slice(1), e, fn));
    } catch (err) { if (!res.headersSent) responde(500, { ok: false, erro: err.message.slice(0, 300) }); }
  });
}).listen(PORTA, "127.0.0.1", () => log(`coletor em http://127.0.0.1:${PORTA}`));
