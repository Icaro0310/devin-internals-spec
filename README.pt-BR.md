# devin-internals-spec

> **Projeto comunitário não oficial.** Sem afiliação, endosso ou patrocínio da
> Cognition AI. "Devin" é marca registada da Cognition AI.

**[English](README.md)** · Português (BR)

Um mapa documentado dos stores locais de sessão do Devin — a `sessions.db` do
CLI, os `acp-messages/*.db` e o `state.vscdb` do Desktop — mais um detector de
versão de schema e fixtures sintéticas determinísticas, para que ferramentas
falhem alto em vez de lerem os teus dados errado em silêncio.

## O problema

Tudo o que o Devin guarda no teu disco vive em bases SQLite não documentadas
cujo schema **muda sem aviso**: a `sessions.db` já passou por **17 migrações**
(v1–v15 em 2026-05-06, v16 em 2026-07-05, v17 em 2026-09-14). Qualquer
ferramenta que leia estes stores tem de fazer engenharia reversa do formato — e
quando a Cognition lança a próxima migração, essas ferramentas quebram *em
silêncio*: contagens erradas, linhas perdidas ou interpretação corrompida, sem
nenhum erro.

O Devin Desktop está ainda pior que o CLI: os seus stores
(`acp-messages/*.db`, `state.vscdb`, locks de sessão, o ledger de migrações
`refinery_schema_history`) não estão documentados em lado nenhum.

## Trabalho anterior (prior art)

Já existe tooling de session-logs para outros CLIs de agentes — por exemplo o
**tokmesh** e o **UniSessions** documentam e fazem parsing da `sessions.db` do
CLI do Devin. Este projeto não reinventa isso: adapta a mesma ideia (schema
SQLite → parsing tipado) e estende-a ao que essas ferramentas não cobrem — os
stores do Desktop — e acrescenta a peça que lhes falta: um **gate explícito de
versão de schema**, para que o parser se recuse a correr contra um schema que
nunca viu.

## O que o torna Devin-native

O diferencial, numa frase: *é o mapa do que o Devin guarda no teu disco — e
avisa quando isso muda.*

1. **Lado a lado:** cobre `acp-messages/*.db`, `state.vscdb` (chaves
   `windsurfSpace.*`) e `refinery_schema_history`, que nenhuma ferramenta
   existente documenta.
2. **Sem Devin:** tira o Devin e não há store para documentar — o extra
   desaparece por completo.
3. **Falha alta:** `detect_schema_version()` devolve um contrato de versão e
   levanta erro em qualquer versão desconhecida, em vez de adivinhar bytes.

## Instalação

```bash
pipx install devin-internals-spec   # quando for publicado no PyPI
```

Para desenvolvimento:

```bash
pip install -e ".[dev]"
pytest
```

## Uso

```bash
devin-inspect schema   <sessions.db>      # contrato de deteção de schema (JSON)
devin-inspect sessions <sessions.db>      # lista sessões (id, título, cwd, …)
devin-inspect health   <devin-data-dir>   # localiza + verifica os 3 stores
```

Todos os subcomandos são read-only e aceitam `--json`. A biblioteca Python é a
interface suportada — o CLI é um wrapper fino:

```python
from devin_internals import detect_schema_version
from devin_internals.parsers import SessionsStore

detect_schema_version("~/AppData/Roaming/devin/cli/sessions.db")
# {"schema_version": 17, "known": True, "min_supported": 15, ...}

with SessionsStore("~/AppData/Roaming/devin/cli/sessions.db") as store:
    store.sessions()  # dataclasses tipadas
```

## Suporte de plataformas

Python stdlib puro — comportamento idêntico em Windows, Linux e macOS. O
CI corre a suite em `windows-latest` + `ubuntu-latest`; o ficheiro ou
diretório alvo é sempre um argumento explícito, sem paths
específicos de plataforma.

## Limitações

- **Internals privados e voláteis.** Estes stores são detalhe de implementação
  do Devin; o schema pode mudar em qualquer release. Só o que está marcado como
  "verificado" em `docs/SPEC.md` deve ser considerado estável.
- **Verificado apenas contra o schema v17** (o mais recente à data). O detector
  *recusa* versões que não conhece — é propositado, mas significa que releases
  novos do Devin vão quebrar a deteção até a spec ser atualizada.
- **Read-only.** Este projeto nunca escreve nas bases de dados do Devin.
- **Não é um exportador de sessões.** Documenta e protege o formato; não faz
  dump das tuas conversas (isso é trabalho do `devin-history`).
- As fixtures contêm **apenas dados sintéticos** — conteúdo real de sessões
  nunca é copiado, por desenho.

## Desenvolvimento

```bash
pip install -e ".[dev]"
pytest
```

Regras base em [CONTRIBUTING.md](CONTRIBUTING.md): fixtures antes de parsers,
commits pequenos, docs bilingues.

## Licença

MIT — vê [LICENSE](LICENSE).
