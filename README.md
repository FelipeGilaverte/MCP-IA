# automation-intel-mcp

O `automation-intel-mcp` expõe dois servidores MCP separados:

- `automation-intel-research`: motor geral de pesquisa e inteligência
- `automation-intel-agency`: motor comercial e operacional da agência

Essa separação é intencional.

- O Research MCP é genérico e evidence-first.
- O Research MCP usa a Perplexity principalmente para busca e coleta de evidências.
- O GPT/OpenAI faz a análise, a comparação, o ranking e a síntese final depois.
- O Agency MCP trabalha com scraping, análise local e heurísticas.
- O Agency MCP pode consultar o Research MCP opcionalmente, de forma conservadora.

## Arquitetura

### Research MCP

O Research MCP é um `execution engine` de pesquisa.

Ele faz:

- executar buscas
- aceitar `subqueries` e `focus_topics` quando o host fornece
- extrair páginas
- deduplicar e normalizar fontes
- classificar estruturalmente as fontes
- pré-rankear tecnicamente
- clusterizar evidência de forma leve
- detectar contradições estruturais simples
- registrar custo, métricas e warnings
- persistir payloads completos por `run_id`

Ele não faz:

- decomposição conceitual principal da pesquisa
- ranking analítico final
- síntese estratégica
- resposta final ao usuário
- orquestração autônoma

Tools do Research MCP:

- `research_raw_search`
- `web_extract_url`
- `graph_run_research`
- `research_get_run`
- `system_budget_status`

### Agency MCP

Responsabilidades principais:

- analisar sites públicos de empresas
- extrair contatos, formulários, CTA e sinais de serviço
- inferir maturidade digital básica
- identificar dores e oportunidades de automação
- gerar oferta e outreach
- opcionalmente usar evidência do Research MCP

Quando o Agency usa pesquisa externa, ele não contamina o core de research. Em vez disso, injeta `extra_subqueries` específicas de negócio.

Tools do Agency MCP:

- `agency_score_niche`
- `agency_analyze_company`
- `agency_generate_offer`
- `agency_generate_outreach`
- `system_budget_status`

### Servidor combinado legado

- módulo: `automation_intel_mcp.server`
- mantido apenas por compatibilidade
- não é a arquitetura recomendada

## Modos de pesquisa

O caminho padrão usa número de buscas normais, não síntese da Perplexity.

- `auto`: adaptativo, mínimo 3 buscas, alvo suave 6, máximo 8
- `quick`: até 4 buscas
- `standard`: até 8 buscas
- `deep`: até 15 buscas
- `exhaustive`: até 40 buscas, uso manual apenas

Defaults e regras:

- o modo público padrão é `auto`
- `auto` se comporta mais perto de `quick` ou `standard` conforme complexidade e cobertura
- `exhaustive` exige aprovação explícita via `--allow-exhaustive`
- o motor para cedo por diminishing returns, repetição de domínios, duplicação de evidência, cobertura suficiente, cap de execução ou hard budget mensal

## Segurança de premium e síntese

Estas proteções continuam valendo:

- `research_quick_search` não faz parte da superfície MCP
- `research_deep_search_expensive` também não faz parte da superfície MCP

Isso impede que o GPT chame helpers caros de síntese da Perplexity acidentalmente via MCP.

A pesquisa premium cara continua existindo apenas como caminho manual:

- não é registrada como tool MCP
- fica disponível só por CLI
- é controlada por `ENABLE_PREMIUM_RESEARCH_TOOLS=false` por padrão
- mesmo habilitada, ainda exige `--confirm-expensive`

## Raw search

A quantidade de resultados retornados por busca é configurável.

- arquivo: `src/automation_intel_mcp/config.py`
- variável Python: `perplexity_raw_search_max_results`
- variável de ambiente: `PERPLEXITY_RAW_SEARCH_MAX_RESULTS`
- valor padrão: `10`

O `research_raw_search` retorna, quando disponível:

- `title`
- `url`
- `canonical_url`
- `snippet`
- `date`
- `source_type`
- `relevance_score`
- `credibility_score`
- `freshness_score`
- `final_score`

Você também pode sobrescrever por chamada:

```bash
automation-intel rawsearch "clinicas odontologicas em sao paulo" --max-results 5
```

## web_extract_url

`web_extract_url` retorna um payload enriquecido com:

- `canonical_url`
- `extraction_quality`
- `content_length_chars`
- `language`
- `published_at`
- `last_updated`
- `title`
- `main_text`
- `content_hash`

Isso ajuda em dedupe, cache e auditoria.

## graph_run_research

`graph_run_research` continua sendo a tool principal do Research MCP, mas agora funciona como executor robusto.

Entrada compatível:

```json
{
  "question": "compare clinic CRMs in Brazil",
  "mode": "auto"
}
```

Entrada estruturada opcional:

```json
{
  "question": "compare clinic CRMs in Brazil",
  "subqueries": [
    "crm para clinicas odontologicas brasil",
    "pricing of clinic CRM vendors in Brazil"
  ],
  "focus_topics": ["vendors", "pricing", "growth"],
  "mode": "auto",
  "execution_cost_cap_usd": 0.5,
  "allow_exhaustive": false
}
```

Regras:

- se `subqueries` vierem do host, elas ganham prioridade prática
- se `subqueries` não vierem, o comportamento compatível é mantido
- o MCP não vira planner semântico forte

## run_id, envelope e recuperação

Toda execução do `graph_run_research` agora gera um `run_id`.

Esse `run_id` aparece em:

- retorno da tool
- logs
- métricas
- tracking de custo
- persistência local

O retorno padrão agora é um envelope operacional compacto, com:

- `run_id`
- `input`
- `search_plan`
- `results`
- `top_sources`
- `clusters`
- `contradictions`
- `gaps`
- `warnings`
- `metrics`
- `budget`
- `storage`
- `raw_evidence_preview`

O payload completo continua armazenado e pode ser recuperado depois com:

- `research_get_run`

ou pela CLI:

```bash
automation-intel get-run research_20260309_abc123
```

## Budget e custo

O sistema preserva o tracker existente e expõe mais transparência.

`system_budget_status` agora retorna:

- `month_total_usd`
- `today_total_usd`
- `last_run_cost_usd`
- `runs_this_month`
- `provider_breakdown`
- `caps`
- `status`

Cada run do graph também devolve:

- `provider_search_cost_usd`
- `provider_extraction_cost_usd`
- `total_cost_usd`
- `cost_cap_usd`
- `cost_source`

## Configuração

Crie o `.env` a partir do `.env.example`.

```bash
cp .env.example .env
```

Setup mínimo:

- `PERPLEXITY_API_KEY`

Configurações importantes:

- `RESEARCH_DEFAULT_MODE`
- `RESEARCH_AUTO_MIN_SEARCHES`
- `RESEARCH_AUTO_SOFT_TARGET_SEARCHES`
- `RESEARCH_AUTO_MAX_SEARCHES`
- `RESEARCH_QUICK_MAX_SEARCHES`
- `RESEARCH_STANDARD_MAX_SEARCHES`
- `RESEARCH_DEEP_MAX_SEARCHES`
- `RESEARCH_EXHAUSTIVE_MAX_SEARCHES`
- `RESEARCH_DEFAULT_EXECUTION_COST_CAP_USD`
- `PERPLEXITY_RAW_SEARCH_MAX_RESULTS`
- `ENABLE_PREMIUM_RESEARCH_TOOLS`
- `BUDGET_SOFT_LIMIT_USD`
- `BUDGET_HARD_LIMIT_USD`
- `CACHE_ENABLED`
- `CACHE_DIR`
- `CACHE_TTL_HOURS`

Configurações de publicação HTTP para MCP remoto:

- `MCP_STATELESS_HTTP`
- `MCP_JSON_RESPONSE`
- `RESEARCH_MCP_HTTP_HOST`
- `RESEARCH_MCP_HTTP_PORT`
- `RESEARCH_MCP_HTTP_PATH`
- `RESEARCH_MCP_PUBLIC_BASE_URL`
- `AGENCY_MCP_HTTP_HOST`
- `AGENCY_MCP_HTTP_PORT`
- `AGENCY_MCP_HTTP_PATH`
- `AGENCY_MCP_PUBLIC_BASE_URL`

## CLI

Pesquisa evidence-first:

```bash
automation-intel research "compare clinic CRMs in Brazil" --json
```

Buscar por `run_id`:

```bash
automation-intel get-run research_20260309_abc123
```

Análise de empresa com pesquisa externa conservadora:

```bash
automation-intel company "Empresa X" "https://empresa.com.br" "clinica odontologica" --external-research --external-research-mode auto
```

Subir MCPs locais por `stdio`:

```bash
automation-intel runserver-research
automation-intel runserver-agency
```

Subir MCPs remotos por Streamable HTTP:

```bash
automation-intel runserver-research-http --host 0.0.0.0 --port 8000 --public-base-url https://research.seudominio.com
automation-intel runserver-agency-http --host 0.0.0.0 --port 8001 --public-base-url https://agency.seudominio.com
```

## ChatGPT

Para conectar no ChatGPT, o MCP precisa estar remoto e acessível por HTTPS público.

Fluxo recomendado:

1. configure o `.env`
2. publique cada MCP em uma URL própria
3. teste o endpoint remoto
4. ative `Developer mode` no ChatGPT
5. adicione os MCPs remotos no ChatGPT

Exemplo de `.env` para deploy:

```env
PERPLEXITY_API_KEY=your_key_here

RESEARCH_MCP_HTTP_HOST=0.0.0.0
RESEARCH_MCP_HTTP_PORT=8000
RESEARCH_MCP_HTTP_PATH=/mcp
RESEARCH_MCP_PUBLIC_BASE_URL=https://research.seudominio.com

AGENCY_MCP_HTTP_HOST=0.0.0.0
AGENCY_MCP_HTTP_PORT=8001
AGENCY_MCP_HTTP_PATH=/mcp
AGENCY_MCP_PUBLIC_BASE_URL=https://agency.seudominio.com
```

Endpoints esperados:

- `https://research.seudominio.com/mcp`
- `https://agency.seudominio.com/mcp`

## Artefatos locais

Os itens abaixo são locais e não devem entrar na distribuição do código-fonte:

- `.env`
- `.cache/`
- `.venv/`
- `.pytest_cache/`
- `__pycache__/`
- `*.pyc`

Mantenha o `.env.example` no projeto. Mantenha seu `.env` local na sua máquina. Não inclua o `.env` real em repositórios, zips ou distribuição de código-fonte.
#   M C P -  
 