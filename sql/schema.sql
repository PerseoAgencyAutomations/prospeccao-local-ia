-- Prospecção local: estado de cada negócio, lote e ledger de custo. Supabase (mesmo banco do contas-a-pagar), schema pl.
-- Aplicar: automations/contas-a-pagar/build/pg.sh -f automations/pesquisa-local/sql/schema.sql
create schema if not exists pl;

create table if not exists pl.lotes (
  id          serial primary key,
  criado_em   timestamptz not null default now(),
  fechado_em  timestamptz,
  nicho       text not null,
  cidade      text not null,
  uf          text not null default 'SP',
  termos      text[] not null,
  exclusoes   text[] not null default '{}',
  max_lugares int not null default 60,
  eval        boolean not null default false,
  retrato     text,                       -- só eval: nome do retrato congelado que o coletor serve
  contagens   jsonb,
  custo_usd   numeric(12,6)
);

-- etapa: qualificado | recusado | pendente | aprovado | descartado | no_crm
create table if not exists pl.negocios (
  id            serial primary key,
  lote_id       int not null references pl.lotes(id),
  place_id      text not null,
  nome          text not null,
  categoria     text,
  telefone      text,
  site          text,
  cidade        text,
  nota          numeric(2,1),
  avaliacoes    int,
  url_maps      text,
  etapa         text not null,
  motivo        text,
  presenca      jsonb,
  achados       jsonb,                    -- conferidos: {tipo, texto, trecho, fonte}
  descartados   jsonb,                    -- o que a IA disse e o código não aceitou, com o porquê
  ficha         text,
  abertura_ok   boolean,
  modelos       jsonb,                    -- quem respondeu em cada etapa
  hubspot_id    text,
  motivo_humano text,
  criado_em     timestamptz not null default now(),
  atualizado_em timestamptz not null default now(),
  unique (lote_id, place_id)
);
create index if not exists negocios_place on pl.negocios(place_id);

-- ledger: uma linha por chamada de IA, com o custo que o OpenRouter devolve em usage.cost
create table if not exists pl.chamadas (
  id         serial primary key,
  lote_id    int not null references pl.lotes(id),
  place_id   text,
  etapa      text not null,               -- categoria | achados | achados_reserva | abertura
  modelo     text,
  ok         boolean not null,
  custo_usd  numeric(12,8) not null default 0,
  tokens_in  int,
  tokens_out int,
  erro       text,
  criado_em  timestamptz not null default now()
);
create index if not exists chamadas_lote on pl.chamadas(lote_id);

-- abre um lote novo, ou devolve o que vai ser retomado (o que já tem etapa final é pulado)
create or replace function pl.abre_lote(p jsonb) returns table(lote_id int, retomado boolean, feitos text[], vistos text[]) language plpgsql as $$
declare l int; ev boolean := coalesce((p->>'eval')::boolean, false);
begin
  if nullif(p->>'retomar', '') is not null then
    select id into l from pl.lotes where id = (p->>'retomar')::int and fechado_em is null;
    if l is null then raise exception 'lote % não existe ou já foi fechado', p->>'retomar'; end if;
    return query select l, true,
      coalesce((select array_agg(n.place_id) from pl.negocios n where n.lote_id = l), '{}'),
      coalesce((select array_agg(distinct n.place_id) from pl.negocios n join pl.lotes o on o.id = n.lote_id where not o.eval and o.id <> l and not ev), '{}');
    return;
  end if;
  insert into pl.lotes(nicho, cidade, uf, termos, exclusoes, max_lugares, eval, retrato)
  values (p->>'nicho', p->>'cidade', coalesce(nullif(p->>'uf', ''), 'SP'),
          array(select jsonb_array_elements_text(p->'termos')), array(select jsonb_array_elements_text(p->'exclusoes')),
          coalesce((p->>'max')::int, 60), ev, nullif(p->>'retrato', ''))
  returning id into l;
  -- negócio já visto num lote de verdade não volta (lote de eval não conta e não é filtrado)
  return query select l, false, '{}'::text[],
    case when ev then '{}'::text[] else coalesce((select array_agg(distinct n.place_id) from pl.negocios n join pl.lotes o on o.id = n.lote_id where not o.eval), '{}') end;
end $$;

create or replace function pl.guarda_negocio(p jsonb) returns table(id int, etapa text) language sql as $$
  with c as (
    insert into pl.chamadas(lote_id, place_id, etapa, modelo, ok, custo_usd, tokens_in, tokens_out, erro)
    select (p->>'lote_id')::int, p->>'place_id', x->>'etapa', x->>'modelo', coalesce((x->>'ok')::boolean, false),
           coalesce((x->>'custo')::numeric, 0), (x->>'tokens_in')::int, (x->>'tokens_out')::int, x->>'erro'
    from jsonb_array_elements(coalesce(p->'chamadas', '[]')) x
    returning 1
  )
  insert into pl.negocios(lote_id, place_id, nome, categoria, telefone, site, cidade, nota, avaliacoes, url_maps, etapa, motivo,
                          presenca, achados, descartados, ficha, abertura_ok, modelos)
  values ((p->>'lote_id')::int, p->>'place_id', p->>'nome', p->>'categoria', p->>'telefone', p->>'site', p->>'cidade',
          (p->>'nota')::numeric, (p->>'avaliacoes')::int, p->>'url_maps', p->>'etapa', p->>'motivo',
          p->'presenca', p->'achados', p->'descartados', p->>'ficha', (p->>'abertura_ok')::boolean, p->'modelos')
  on conflict (lote_id, place_id) do update set etapa = excluded.etapa, motivo = excluded.motivo, presenca = excluded.presenca,
     achados = excluded.achados, descartados = excluded.descartados, ficha = excluded.ficha, abertura_ok = excluded.abertura_ok,
     modelos = excluded.modelos, atualizado_em = now()
  returning id, etapa
$$;

create or replace function pl.fecha_lote(l int) returns jsonb language sql as $$
  update pl.lotes set fechado_em = now(),
    contagens = (select jsonb_object_agg(etapa, n) from (select etapa, count(*) n from pl.negocios where lote_id = l group by etapa) t),
    custo_usd = (select coalesce(sum(custo_usd), 0) from pl.chamadas where lote_id = l)
  where id = l
  returning jsonb_build_object('lote', id, 'contagens', contagens, 'custo_usd', custo_usd)
$$;
