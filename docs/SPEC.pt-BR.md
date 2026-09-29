# SPEC 01 — `devin-internals-spec` (Vaga 0)

## 1. Problema

Ninguém consegue construir ferramentas Devin fiáveis porque o formato dos dados
locais não é público e **muda**: a `sessions.db` já teve **17 migrações**
(v1–v15 em 2026-05-06, v16 em 2026-07-05, v17 em 2026-09-14). Documentação
existente (tokmesh, UniSessions) cobre **apenas o CLI** — o store do **Devin
Desktop** (`acp-messages/*.db`, `state.vscdb`, locks, `refinery_schema_history`)
não está documentado em lado nenhum.

Evidência: a auditoria de hoje teve de descobrir o schema por engenharia reversa,
e as ferramentas existentes quebram silenciosamente quando o schema muda.

## 2. Extra Devin (e os 3 testes)

**Extra:** é o **único mapa do store do Devin Desktop/GUI**, e inclui um
**detector de versão** que faz qualquer ferramenta falhar com mensagem clara em
vez de corromper dados.

- **Concorrente lado a lado:** tokmesh/UniSessions documentam o CLI; **não** cobrem
  `acp-messages`, `state.vscdb` (`windsurfSpace.*`), locks órfãos nem
  `refinery_schema_history`. A nossa faz algo que elas não conseguem.
- **Sem Devin:** se retirarmos o Devin, não há store para documentar — o extra desaparece.
- **Uma frase:** *"É o mapa do que o Devin guarda no teu disco — e avisa quando isso muda."*

## 3. Escopo

- Spec dos **3 stores**: `sessions.db`, `acp-messages/*.db`, `state.vscdb`.
- Diagrama ER + descrição campo a campo das tabelas relevantes
  (`sessions`, `message_nodes`, `tool_call_state`, `refinery_schema_history`,
  `meta`/`messages` GUI, chaves `windsurfSpace.*`).
- **Detector de versão**: lê `refinery_schema_history` + `app_state.schema_compat_version`;
  falha alto em versão desconhecida.
- **Gerador de fixtures**: cria DBs sintéticas mínimas e válidas (v15/v16/v17),
  + `acp-messages` e `state.vscdb` mínimos.
- **CLI `devin-inspect`**: `schema`, `sessions`, `health` (read-only).

## 4. NÃO-escopo

- Não analisa nem exporta conteúdo de sessões (isso é `devin-history`).
- Não escreve na DB (read-only, sempre).
- Não documenta o formato de plugins/skills (isso é da Cognition, já publicado).
- Não é MCP na v1 (MCP read-only fica para depois, se houver pedido).

## 5. Interfaces

| Interface | Descrição |
|---|---|
| **Biblioteca** `devin_internals` | Parsing + deteção de versão (fonte de verdade para outros repos) |
| **CLI** `devin-inspect` | `schema` · `sessions` · `health` |
| **Docs** | `SPEC.md` (o documento público) + `SCHEMA.md` |
| **PyPI** | `pipx install devin-internals-spec` |

## 6. Formato de saída / contrato de dados

- `SPEC.md`: documento versionado (`spec v0.1`) — aberto a RFC.
- Detector devolve `{"schema_version": 17, "known": true, "min_supported": 15}`.
- Fixtures: ficheiros `.db` gerados, determinísticos (seed fixa), versionados no repo.

## 7. Fixtures e testes (TDD — fixtures primeiro)

1. Gerador de `sessions.db` sintético (com as 17 migrações aplicadas).
2. Fixtures por versão: v15, v16, v17 (para testar compatibilidade).
3. Fixture `acp-messages` (meta + messages) e `state.vscdb` mínimos.
4. Testes: deteção de versão · parsing de cada tabela · **falha clara** em versão
   desconhecida · idempotência do gerador · encoding/paths Windows.
5. CI: Windows + Linux.

## 8. Riscos e mitigação

| Risco | Mitigação |
|---|---|
| Schema muda | Detector de versão + fixtures por versão + CI noturno local |
| Documentação ficar errada | Marcar cada campo como "verificado em vX"; changelog de spec |
| Termos de uso (ler DB local) | Verificar termos; read-only; zero rede; documentar no SECURITY.md |
| Alguém depender de campo não documentado | Publicar só o que é verificado; marcar o resto como "instável" |

## 9. Critério de "pronto"

- [ ] `SPEC.md` publicada com os 3 stores documentados
- [ ] Detector falha alto em versão desconhecida (teste dedicado)
- [ ] Fixtures v15/v16/v17 geram DBs válidas e abrem com o parser
- [ ] `devin-inspect health` corre em Windows e Linux
- [ ] Testes verdes em Windows + Linux · README (EN) com Prior art e Limitations
- [ ] `pipx install devin-internals-spec` funciona

## 10. Tarefas (ordem)

1. Gerador de fixtures (v17) + teste de abertura.
2. Parser de `sessions.db` + `refinery_schema_history` → detector de versão.
3. Fixtures v15/v16 + testes de compatibilidade.
4. Parser de `acp-messages` e `state.vscdb`.
5. Escrever `SPEC.md`/`SCHEMA.md` (EN).
6. CLI `devin-inspect`.
7. Publicar PyPI + repo + CI.
