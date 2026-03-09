# Prompts para continuar o projeto no Codex / Cursor / outro agente

## Prompt 1 — melhorar análise de empresa

Melhore o projeto atual `automation-intel-mcp`.
Objetivo: fortalecer a tool `agency_analyze_company`.

Tarefas:
1. extrair e-mails, telefone, WhatsApp e formulários do HTML
2. identificar CTA principal do site
3. inferir maturidade digital básica
4. separar dores em categorias: comercial, operacional, atendimento, marketing
5. retornar JSON estruturado e estável
6. criar testes unitários para a lógica de parsing

Restrições:
- mantenha compatibilidade com Python 3.11+
- não coloque segredo no código
- preserve a CLI existente
- preserve o servidor MCP existente

## Prompt 2 — adicionar Google Maps / Places

Adicione integração opcional com Google Places ao projeto `automation-intel-mcp`.
Objetivo: enriquecer a prospecção local.

Tarefas:
1. criar serviço `google_places.py`
2. criar tool MCP `agency_find_local_businesses`
3. receber nicho + cidade + raio
4. retornar nome, endereço, site, telefone, rating, total de reviews
5. adicionar env vars em `.env.example`
6. documentar custo estimado no README

## Prompt 3 — adicionar propostas comerciais mais fortes

No projeto `automation-intel-mcp`, crie uma camada de proposta comercial.

Tarefas:
1. criar tool `agency_generate_offer`
2. entrada: nicho, dor, solução, ticket desejado, nível de urgência
3. saída: promessa, entregáveis, objeções prováveis, argumento de ROI, CTA final
4. incluir versões para WhatsApp, e-mail e call discovery
5. documentar no README

## Prompt 4 — adicionar modo em lote com controle de custo

No projeto `automation-intel-mcp`, implemente análise em lote.

Tarefas:
1. criar comando CLI `batch-company`
2. aceitar CSV com `company_name,company_url,niche`
3. limitar custo total por execução
4. parar automaticamente ao atingir limite configurado
5. salvar saída em JSONL
6. usar cache para evitar repetir chamadas
