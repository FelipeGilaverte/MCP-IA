# automation-intel-mcp

O `automation-intel-mcp` expõe dois servidores MCP separados de propósito:

- `automation-intel-research`: motor geral de pesquisa e inteligência
- `automation-intel-agency`: motor comercial e operacional da agência

Essa separação é intencional.

- O Research MCP é genérico e não é exclusivo da agência.
- O Research MCP usa a Perplexity principalmente para busca e coleta de evidências.
- O GPT/OpenAI deve fazer o raciocínio, a síntese, a comparação e o ranking depois.
- O Agency MCP trabalha principalmente com scraping, análise local e heurísticas.
- O Agency MCP pode consultar o Research MCP opcionalmente, com defaults conservadores.

## Arquitetura

### Research MCP

O fluxo padrão do Research MCP é evidence-first:

1. classifica a intenção
2. começa com um plano leve
3. gera subqueries neutras
4. roda buscas raw na Perplexity
5. deduplica fontes e snippets
6. para cedo quando a cobertura já é suficiente ou quando o budget manda parar
7. retorna evidência estruturada para o GPT/OpenAI raciocinar depois

Regras importantes:

- o fluxo padrão não chama a Perplexity de novo para sintetizar uma resposta final
- o fluxo padrão usa apenas raw search
- o modo público padrão é `auto`
- `research_quick_search` não faz parte da superfície MCP
- pesquisa premium cara da Perplexity não fica exposta via MCP por padrão
- o core de research é neutro de domínio

Tools do Research MCP:

- `research_raw_search`
- `web_extract_url`
- `graph_run_research`
- `system_budget_status`

### Agency MCP

Responsabilidades principais:

- analisar sites públicos de empresas
- extrair contatos, formulários, CTA e sinais de serviço
- inferir maturidade digital básica
- identificar dores e oportunidades de automação
- gerar oferta e outreach
- opcionalmente usar evidência do Research MCP

Quando o Agency usa pesquisa externa, ele não contamina o core genérico de research. Em vez disso, injeta `extra_subqueries` específicas de negócio na camada da agência.

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

## Quantidade de resultados do raw search

A quantidade de resultados retornados por busca é configurável.

- arquivo: `src/automation_intel_mcp/config.py`
- variável Python: `perplexity_raw_search_max_results`
- variável de ambiente: `PERPLEXITY_RAW_SEARCH_MAX_RESULTS`
- valor padrão: `10`

Você também pode sobrescrever por chamada:

```bash
automation-intel rawsearch "clinicas odontologicas em sao paulo" --max-results 5
```

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
- `AGENCY_ENABLE_EXTERNAL_RESEARCH`
- `AGENCY_EXTERNAL_RESEARCH_DEFAULT_MODE`
- `AGENCY_EXTERNAL_RESEARCH_MAX_MODE`
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

Entry points diretos:

```bash
automation-intel-research-http
automation-intel-agency-http
```

## Formato padrão da saída de research

O graph padrão retorna evidência estruturada para o GPT/OpenAI raciocinar depois, incluindo:

- `query`
- `intent`
- `mode_requested`
- `mode_used`
- `search_strategy`
- `min_searches`
- `max_searches`
- `search_calls`
- `subqueries`
- `results_by_subquery`
- `deduped_sources`
- `coverage_summary`
- `findings`
- `gaps_or_uncertainties`
- `suggested_next_steps`
- `usage`

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

Start commands:

```bash
automation-intel runserver-research-http --host 0.0.0.0 --port 8000 --public-base-url https://research.seudominio.com
```

```bash
automation-intel runserver-agency-http --host 0.0.0.0 --port 8001 --public-base-url https://agency.seudominio.com
```

Endpoints esperados:

- `https://research.seudominio.com/mcp`
- `https://agency.seudominio.com/mcp`

Observações práticas:

- a recomendação é publicar os dois MCPs separadamente
- o Research MCP costuma ser o primeiro a subir
- o Agency MCP pode ser publicado depois, quando você quiser usar a camada comercial no ChatGPT
- o projeto já fica pronto para Streamable HTTP; falta apenas escolher onde hospedar

## Deploy rápido

Um fluxo simples em VPS, Railway, Render, Fly.io ou similar:

1. instalar Python 3.11+
2. instalar o projeto
3. configurar as variáveis de ambiente
4. expor a porta do processo
5. iniciar um dos comandos HTTP acima
6. colocar HTTPS na frente

Se a plataforma injeta a porta em variável de ambiente, reflita isso no comando de start ou nas env vars.

## Artefatos locais

Os itens abaixo são locais e não devem entrar na distribuição do código-fonte:

- `.env`
- `.cache/`
- `.venv/`
- `.pytest_cache/`
- `__pycache__/`
- `*.pyc`

Mantenha o `.env.example` no projeto. Mantenha seu `.env` local na sua máquina. Não inclua o `.env` real em repositórios, zips ou distribuição de código-fonte.
#   M C P - I A  
 #   M C P - I A  
 #   M C P - I A  
 