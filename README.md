# Prospecção local com IA (n8n + Google Maps + HubSpot)

O vendedor digita nicho e cidade. Em uns 15 minutos, recebe os negócios que valem uma ligação. Cada um vem com o porquê: um trecho do site ou das avaliações, conferido em código. O lead só entra no HubSpot depois que ele aprova.

> **Eval com 40 negócios reais de Sorocaba: 39/40 certos, 0 lead qualificado sem evidência, 0 trecho que não esteja na fonte, injeção numa avaliação sem efeito. US$ 0,00008 por 40 negócios.** Detalhe em [`eval/RELATORIO.md`](eval/RELATORIO.md).

## O problema

Prospectar negócio local à mão leva uns 10 minutos por lugar:
- abrir o Maps e conferir se tem site;
- buscar o nome no Google, porque o "sem site" do Maps erra;
- ler as avaliações e decidir se vale ligar;
- anotar o que falar.

Com 60 por semana, são 520 horas por ano. O PAT (Process Assessment Tool) deu **Low Hanging Fruit**, com 224 horas liberadas por ano (`pat-respostas.json`).

## Como funciona

```
Formulário: nicho, cidade, termos, exclusões
   ↓
Coletor local (Chromium, sem API paga) varre o Maps ──→ o n8n espera no Wait até ele terminar
   ↓ um negócio por vez (o lote retoma do ponto onde parou se cair)
Regra em código: fechado, nota < 4,5, < 10 avaliações, sem telefone, palavra excluída → recusado com motivo
   ↓ categoria ambígua ("Eletricista", "Climatização")? a IA classifica, citando o nome ou a categoria
Busca pelo nome + site + 5 avaliações (coletor)
   ↓ presença conferida em código: sem site, só rede social, site fraco, fora do ar, desatualizado ou bom
IA lê site e avaliações → achados, cada um com trecho literal
   ↓ código confere o trecho na fonte (palavra inteira); formato errado → reserva; frase de instrução → descarte
Decisão em código: qualificado / recusado + motivo / pendente
   ↓ qualificado: a IA escreve a abertura da ligação só com marcadores ({avaliacoes}, {achado_1}); número escrito por ela barra a abertura
Postgres: estado de cada negócio + ledger de custo (usage.cost de cada chamada)
   ↓
[P2] você aprova numa página com as fichas → HubSpot: empresa + tarefa "Ligar" com a ficha no corpo
```

## Onde a IA entra e onde não entra

| Etapa | Quem faz | Por quê |
|---|---|---|
| Nota, avaliações, telefone, exclusões | código | regra fixa, não precisa de IA |
| A categoria é do nicho? | IA, só quando ambígua | "Prestador de serviços de climatização" pede leitura |
| Tem site? | código + busca | o campo do Maps erra; domínio é comparado com o nome |
| O que dizer na ligação | IA, com trecho | texto livre das avaliações; o trecho é conferido |
| Ligar ou não | código | a decisão não depende do humor do modelo |
| Entrar no CRM | pessoa | nada sai sem aprovação |

## Eval

40 negócios reais de Sorocaba, 20 de ar-condicionado e 20 de veterinária. Os dados de busca, site e avaliações foram congelados, então todo eval roda igual. O gabarito foi escrito antes de rodar o fluxo.

| | Fluxo | Um prompt só (baseline) |
|---|---|---|
| Acerto ligar/não | **39/40** | 38/40 |
| Trecho que não está na fonte | **0, conferido sempre** | 0 neste conjunto, nada confere |
| Custo, 40 negócios | **US$ 0,00008** | US$ 0,00046 |
| Chamadas de IA | 37: 20 negócios nem chegam na IA | 40 |

- **O erro que sobra:** uma clínica-escola de universidade. Passa em toda regra objetiva, e quem a tira é a aprovação humana; no teste do `[P2]`, ela foi descartada.
- **Comparação com o baseline:** quase empata no acerto. O fluxo ganha em garantia (regra em código, trecho sempre conferido), custo e motivo registrado de cada recusa. Com 40 casos, 1 acerto de diferença não é estatística.
- **Caminhos de falha** ([`build/testar_caminhos_p1.py`](build/testar_caminhos_p1.py)), **4/4:**
  - modelo principal fora do ar: a reserva lê;
  - os dois fora do ar: 0 qualificado no escuro, e quem passou na regra fica "pendente";
  - coletor fora do ar: o alerta de erro registra;
  - queda no meio do lote: o "retomar" termina sem duplicar nem repetir chamada de IA.
- **HubSpot** ([`build/testar_p2.py`](build/testar_p2.py)):
  - em 4 lotes de teste, 30 empresas e 30 tarefas "Ligar" criadas pela aprovação, com 0 erro;
  - a clínica-escola foi descartada com motivo;
  - a limpeza do eval apagou as de teste.

## O que deu errado e virou regra

- **`URL()` não existe no Code node do n8n.** O domínio saía vazio, e Instagram e site próprio nunca eram reconhecidos. O teste de unidade passava, porque roda no Node. Só o eval de ponta a ponta pegou.
- **O guia `sorocaba.com.br` contava como site do ar-08, um eletricista com "Sorocaba" no nome.** Domínio feito só de nome de cidade e palavra genérica não vale mais. Já o ar-19 tem site real, mas no Maps aparece sem site. Esse é o "sem site" falso que a busca existe pra pegar.
- **O filtro anti-injeção barrava avaliação real** ("sistema de ar-condicionado", "competente e qualificado"). Agora só barra frase de instrução. A avaliação com injeção não teve efeito em nenhuma rodada.
- **Em replay, o coletor respondia antes de o n8n chegar ao Wait**, e a execução ficava parada. Agora ele tenta de novo até ser aceito.
- **Link do Instagram no campo "site" da HubSpot** fazia a empresa ser tratada como `instagram.com`. Agora o campo só recebe site próprio, e rede social vai na descrição.

## Stack

- **n8n 2.32 local:** `[P1]` coleta e qualifica, `[P2]` aprovação e CRM, `[P3]` limpeza do eval. Erro vai pro `[C9]` do [contas-a-pagar](https://github.com/PerseoAgencyAutomations/contas-a-pagar-ia).
- **Coletor:** Node + Playwright em `127.0.0.1:5681`. O n8n 2.x vem com o Execute Command desligado, então o coletor é um serviço.
- **OpenRouter:** chamado por HTTP Request, pra ler o custo de cada chamada. `particle-ai/particle-1:free` + reserva `google/gemma-3-27b-it`.
- **Postgres no Supabase:** schema `pl`, com estado, retomada e ledger de custo.
- **HubSpot grátis:** chave de serviço, que fica só no n8n.

## Como rodar

1. Postgres: `sql/schema.sql`.
2. Coletor: `coletor/subir.sh` (precisa do `playwright-core`).
3. n8n:
   - credenciais Postgres, OpenRouter e HubSpot Service Key;
   - `python3 build/montar_p1.py` e `python3 build/montar_p2.py`.
4. Use: `http://localhost:5678/form/prospeccao` e, depois, `/form/aprovar-leads`.
5. Testes:
   - `node codigo/teste-pl.js`;
   - `python3 build/rodar_eval_p1.py r1`;
   - `python3 build/baseline.py b1`;
   - `python3 build/testar_p2.py <lote> --limpar`;
   - `python3 build/testar_caminhos_p1.py`.

## Limites

- **Google Maps sem login:** traz 5 avaliações e às vezes uma página reduzida. Login de robô em conta Google suspende a conta, então não é usado.
- **Busca:** a do DuckDuckGo limita pedidos. Busca bloqueada vira "sem evidência", nunca "sem site".
- **Gabarito:** foi rotulado por mim (Claude), e os 4 casos de julgamento esperam conferência humana. O ajuste de prompt do ar-17 (loja de peças) foi feito depois de ver o eval, no mesmo conjunto.
- **Dados reais:** os 40 negócios aparecem como `ar-01` a `vet-20`. Nome, telefone, site, avaliações e o retrato do eval ficam fora do repositório.

---
