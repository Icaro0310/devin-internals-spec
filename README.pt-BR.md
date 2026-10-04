<div align="center">

<img src="assets/banner.svg" alt="devin-internals-spec" width="100%"/>

<a href="https://github.com/Icaro0310/devin-internals-spec/actions/workflows/tests.yml"><img src="https://github.com/Icaro0310/devin-internals-spec/actions/workflows/tests.yml/badge.svg" alt="tests"/></a>
<a href="https://scorecard.dev/viewer/?uri=github.com/Icaro0310/devin-internals-spec"><img src="https://api.scorecard.dev/projects/github.com/Icaro0310/devin-internals-spec/badge" alt="OpenSSF Scorecard"/></a>


</div>

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

Requer Python ≥ 3.10 e `pipx`. **Windows (PowerShell):** instale `pipx` com `py -m pip install --user pipx`, execute `py -m pipx ensurepath` e reabra o terminal. **Linux (Debian/Ubuntu):** execute `sudo apt install pipx python3-venv` e `pipx ensurepath`; reabra o terminal. Noutras distribuições Linux, instale `pipx` pelo gestor de pacotes.

```bash
pipx install "devin-internals-spec @ git+https://github.com/Icaro0310/devin-internals-spec.git"
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
devin-inspect contract <devin-data-dir>   # drift unificado: schema + meta acp
                                          # + shape de usage, um relatório
devin-inspect make-fixture <out>          # stores sintéticos determinísticos
                                          # para testes/demos (--kind, --seed,
                                          # --schema-version, --n-sessions)
```

`contract` é a fronteira única de drift do catálogo: reporta a versão de
schema do `sessions.db`, o `schema_version` do meta dos `acp-messages`
(observado: 6; 1 em DBs legados) e chaves de meta inesperadas, e o shape de
usage verificado (nenhum custo persistido — só `num_tokens_preceding`). No
Linux resolve automaticamente o layout dividido (`~/.local/share/devin` +
`~/.config/Devin`). Exit code ≠ 0 em qualquer drift.

Todos os subcomandos são read-only e aceitam `--json`. A biblioteca Python é a
interface suportada — o CLI é um wrapper fino:

```python
import os
import sys
from pathlib import Path
from devin_internals import detect_schema_version
from devin_internals.parsers import SessionsStore

if os.name == "nt":
    root = Path(os.environ["APPDATA"]) / "devin"
elif sys.platform == "darwin":
    root = Path.home() / "Library" / "Application Support" / "devin"
else:
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    root = data_home / "devin"
sessions_db = root / "cli" / "sessions.db"

detect_schema_version(sessions_db)
# {"schema_version": 17, "known": True, "min_supported": 15, ...}

with SessionsStore(sessions_db) as store:
    store.sessions()  # dataclasses tipadas
```

## Funciona só com o Devin (modo Devin-only)

A spec é documentação mais uma pequena biblioteca local de validação: lê as
stores do Devin para reportar a versão do schema e bloqueia as ferramentas
quando a versão é mais recente que o conhecido — para ruidosamente em vez de
interpretar mal. Puramente local; nada externo é necessário.

## Suporte de plataformas

Python stdlib puro — comportamento idêntico em Windows, Linux e macOS. O
CI corre a suite em `windows-latest` + `ubuntu-latest`; o ficheiro ou
diretório alvo é sempre um argumento explícito, sem paths
específicos de plataforma.


### `vscdb-scan` — auditoria só de forma (IS-1)

`devin-internals vscdb-scan <state.vscdb>` audita o store chave/valor da
GUI e reporta por chave: nome, *forma* do valor (json-object/array/string/…),
tamanho, chaves JSON de topo e flags de risco. **Valores nunca são
impressos** — flags são heurísticas; auditoria real confirmou que
`state.vscdb` pode conter tokens e PII. `--fail-on-flags` sai 1 para CI.

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

## Quando usar

- Você está a construir uma ferramenta que lê os stores locais do Devin e precisa do schema documentado, não de engenharia reversa.
- Você quer um gate de versão de schema: `detect_schema_version()` recusa ruidosamente em versões desconhecidas em vez de interpretar mal.
- Você precisa de fixtures sintéticos determinísticos para testar parsers — sem dados de sessões reais.
- Você precisa de acesso tipado e read-only ao `sessions.db` via `SessionsStore` em Python.

## Quando NÃO usar

- Você quer exportar ou fazer dump de sessões — isto documenta e protege o formato; quem exporta é o `devin-history`.
- A sua versão do Devin traz um schema mais recente que v17 — o detetor recusa por design até a spec o alcançar.
- Você precisa de escritas — cada parser e subcomando é estritamente read-only.

## FAQ

**Que dados o Devin guarda localmente, e onde?** Segundo esta spec: um `sessions.db` versionado sob `cli/` (sessões, estado de tool calls, transcrições), um `acp-messages/*.db` por sessão GUI, um KV store `state.vscdb` com chaves `windsurfSpace.*`, `credentials.toml`, e um ledger de migrações `refinery_schema_history`. Os detalhes verificados vivem em `docs/SPEC.md`.

**O que acontece quando o Devin lança uma nova versão de schema?** Ferramentas que usam esta biblioteca falham ruidosamente, não em silêncio. `detect_schema_version()` devolve um contrato (`known`, `min_supported`) e levanta erro em versões que não reconhece — verificado contra o schema v17 à data de escrita.

**Como é diferente de outros parsers de sessions.db?** Também documenta os stores do Desktop GUI (`acp-messages/*.db`, `state.vscdb`, locks de sessão, o ledger de migrações) que outras ferramentas não cobrem, e adiciona o gate explícito de versão de schema. A biblioteca é a interface suportada; `devin-inspect` é um wrapper CLI fino.

## Licença

MIT — vê [LICENSE](LICENSE).


---

Se isso te poupou tempo de depuração, uma ⭐ no repositório ajuda outras pessoas a encontrá-lo.
