# Pipeline de Extração Financeira de Condomínios

Extrai automaticamente dados financeiros de faturas de condomínio em PDF e consolida tudo em um arquivo Excel auditável.

---

## Visão Geral

O pipeline processa PDFs de diferentes administradoras (cada uma com layout próprio), identifica o modelo automaticamente, extrai os itens de despesa e valida a soma extraída contra o total impresso no documento. Se houver divergência, aciona um mecanismo de fallback independente via `pdfplumber`. O resultado final é um Excel com três abas e linhas divergentes destacadas em vermelho.

```
input_pdfs/          →  pipeline.py  →  output/consolidado_despesas.xlsx
  Modelo1.pdf                              ├── Detalhado       (item a item)
  modelo2.PDF                              ├── Resumo_PDF      (por arquivo)
  modelo3.pdf                              └── Resumo_Bloco    (por bloco)
  modelo4.pdf
```

---

## Modelos de PDF Suportados

| ID         | Administradora / Formato                  | Layout             |
|------------|-------------------------------------------|--------------------|
| `modelo_a` | Condomínio Residencial Alta Vista         | 2 colunas, por apt |
| `modelo_b` | Residencial Itacolomi (Rateio Detalhado)  | 1 coluna, por apt  |
| `modelo_c` | Residencial Porto Onix (Imobiliar)        | Tabela landscape   |
| `modelo_d` | (reservado para expansão)                 | —                  |

Para adicionar um novo modelo, basta criar uma entrada em `config.yaml` com assinaturas e regex, e registrar o parser em `pipeline.py`.

---

## Estrutura do Projeto

```
.
├── pipeline.py                  # Ponto de entrada (CLI via Typer)
├── config.yaml                  # Assinaturas, regex e configurações por modelo
├── layout_detector.py           # Detecção automática de layout (exato + fuzzy)
├── data_validator.py            # Validação financeira + fallback pdfplumber
├── excel_exporter.py            # Geração do Excel consolidado (3 abas)
├── models.py                    # Modelos de dados (Pydantic)
├── utils.py                     # parse_valor_br, group_words_by_line, clean_text
├── parsers/
│   ├── base_parser.py           # Máquina de estados base (IDLE → DESPESAS → TOTAL)
│   ├── modelo_a_parser.py       # Parser para layout de 2 colunas
│   └── modelos_concretos.py     # ModeloB, ModeloC (tabela), ModeloD
├── input_pdfs/                  # PDFs de entrada
└── output/                      # Excel gerado
```

---

## Como Executar

### Pré-requisitos

```bash
pip install pymupdf pdfplumber pydantic typer loguru tqdm openpyxl pandas rapidfuzz pyyaml
```

### Execução

```bash
python pipeline.py --input-dir ./input_pdfs --output-dir ./output
```

| Opção | Padrão | Descrição |
|---|---|---|
| `--input-dir` | `./input_pdfs` | Pasta com os PDFs de entrada |
| `--output-dir` | `./output` | Pasta de saída |
| `--config-file` | `config.yaml` | Arquivo de configuração |
| `--log-level` | `INFO` | Nível de log (`DEBUG`, `INFO`, `WARNING`) |

---

## Como Funciona

### 1. Detecção de Layout

`layout_detector.py` lê a primeira página do PDF e busca **assinaturas** (textos únicos de cada administradora). Se não encontrar correspondência exata, aplica **fuzzy matching** com limiar de 85% via `rapidfuzz` — útil para PDFs com OCR imperfeito.

### 2. Extração de Texto

Dois modos dependendo do layout:

- **`dois_colunas: true`** (modelo_a) — PyMuPDF divide cada página física ao meio e extrai as duas colunas como páginas virtuais independentes. Um PDF de 21 páginas gera 42 páginas virtuais.
- **`dois_colunas: false`** (modelos b, c) — Extração página a página sem divisão geométrica.

### 3. Parsing por Estado

Cada parser implementa uma máquina de estados:

```
IDLE → (encontra APTO/CASA) → READING_DESPESAS → (encontra "Com multa:" / "TOTAL") → READING_TOTAL
```

- Em `READING_DESPESAS`: cada linha é testada contra o regex `item_despesa`. Linhas que não casam mas contêm um valor numérico isolado são guardadas como `subtotal_candidate` (subtotal sem multa).
- Ao encontrar o total: calcula `multa = total - subtotal_candidate` e registra como `ItemDespesa("Multa/Juros", multa)`.
- Após o total: transição para `READING_TOTAL` — nenhuma linha adicional é acumulada (evita capturar rodapés e totais gerais).

### 4. Validação e Fallback

`data_validator.py` compara `soma_calculada` com `total_impresso`. Se a divergência superar a tolerância configurada (padrão: 0,5%):

1. Aciona `pdfplumber` na **página física** do apartamento.
2. Tenta extrair tabelas estruturadas; se vazio, recorre a palavras isoladas.
3. Se o fallback convergir → status `OK`, camada marcada como `HYBRID`.
4. Se não → status `DIVERGENTE`, linha destacada em vermelho no Excel.

### 5. Exportação Excel

Três abas geradas por `excel_exporter.py`:

| Aba | Conteúdo |
|---|---|
| `Detalhado` | Uma linha por item de despesa, com todas as colunas de auditoria |
| `Resumo_PDF` | Totais, acurácia e contagem de divergências por arquivo |
| `Resumo_Bloco` | Totais por bloco físico do condomínio |

Linhas com `Status_Validacao = DIVERGENTE` são coloridas em vermelho automaticamente.

---

## Configuração (`config.yaml`)

```yaml
layouts:
  modelo_a:
    assinaturas: ["TEXTO ÚNICO DO PDF"]   # para detecção automática
    regex_bloco:   "BL\\.\\s*([A-Z0-9]+)"
    regex_apto:    "(?i)(?:CASA|APTO)\\s+(\\d+)"
    regex_total:   "(?i)Com\\s+multa\\s*[:\\s]*([\\d\\.,]+)"
    item_despesa:  "^(\\d+)?\\s*(.*?)\\s+([\\d\\.,]+)\\s*\\S?$"
    dois_colunas:  true

validacao:
  tolerancia_percentual: 0.5   # aceita até 0,5% de divergência
```

---

## Changelog

### [2026-03-21] — Correções de Produção (Zero Divergências)

**Bugs críticos corrigidos:**

- **`parse_valor_br` ignorava sinal negativo** — `-306,16` era lido como `306,16`, inflando a soma de apartamentos com créditos/isenções (ex: modelo_c com `-306,16 Garantia Externa`). Corrigido capturando o sinal na regex.
- **Páginas virtuais vs. físicas no fallback** — Para PDFs de 2 colunas (21 páginas físicas = 42 virtuais), o fallback recebia o número virtual (ex: 37) e tentava abrir `pdfplumber.pages[36]` → `IndexError` silencioso. Corrigido mapeando `physical_page = (i-1) // 2 + 1` e armazenando no apartamento.
- **`ImportError` em `base_parser`** — `from utils import parse_currency` referenciava função inexistente. Corrigido.
- **`taxa_assertividade` sempre 0%** — O campo nunca era calculado. Corrigido em `data_validator.py`.

**Bugs de regex corrigidos:**

- **modelo_b `regex_total`** — Padrão `TOTAL RATEIO` nunca casava com `TOTAL | 328,22`. Corrigido para `(?i)^\s*TOTAL\b[\s\|:]*`.
- **modelo_b `regex_apto`** — Capturava índice sequencial (1, 2, 3) em vez do número do apartamento (101, 102, 103). Corrigido.
- **modelo_c `regex_total`** — Grupo de captura errado retornava o número do apt em vez do valor total. Corrigido.
- **modelo_c `_RE_APT_ROW`** — `\b` casava `292,78` como apartamento `292`. Corrigido exigindo `\s+` após os dígitos.
- **modelo_a `item_despesa`** — Marcadores de rodapé (ex: `19,93 T`) impediam o match por quebrar o âncora `$`. Corrigido com `\s*\S?$`.

**Melhorias de parsing:**

- **modelo_a `subtotal_candidate`** — Pipeline passa a capturar o subtotal sem multa (valor numérico isolado antes de "Com multa:") e deriva a multa/juros como `ItemDespesa`. Elimina a divergência sistemática de ~2% em todos os apartamentos.
- **modelo_a contaminação de cabeçalho** — Colunas direitas de PDFs de 2 colunas iniciavam com cabeçalhos de página (`MARIA LUISA CARVALHO`, `Emitir DOCs: S`...) que corrompiam o buffer `last_desc`. Removido o mecanismo `last_desc` (desnecessário pois todos os itens de modelo_a são de linha única).
- **modelo_b extração de coluna única** — PDF era dividido geometricamente ao meio, destruindo a estrutura de linhas. Corrigido com flag `dois_colunas: false` e função `extract_full_text()`.
- **modelo_c subseções** — PDFs do Imobiliar repetem os mesmos apartamentos em subseções (FUNDO RESERVA, ÁGUA E ESGOTO...) após um separador `---`. Corrigido: separator detectado define `in_subsection=True`; subseções acumulam despesas mas não sobrescrevem `total_impresso`.
- **`subtotal_candidate` cross-page** — Não resetar no início de cada `parse_page` (apenas ao detectar novo apartamento), permitindo que o subtotal capturado no final de uma página virtual seja usado pelo "Com multa:" na próxima.

### [2026-03-15] — Versão Inicial

- Estrutura base: `BasePDFParser`, máquina de estados, `DataValidator` com fallback `pdfplumber`, `ExcelExporter` com 3 abas e formatação condicional.
- Suporte inicial a modelo_a (2 colunas geométricas) e modelo_c (tabela landscape Imobiliar).

---

## Sugestões de Melhorias Futuras

### Prioridade Alta

**1. Interface gráfica (GUI) para Roberta**
O pipeline hoje é CLI. Uma interface simples com `tkinter` ou `PySimpleGUI` permitiria arrastar PDFs, clicar em "Processar" e abrir o Excel diretamente — sem precisar do terminal. O `desktop.py` já existe no projeto e pode ser o ponto de partida.

**2. Corrigir fallback para modelo_a de 2 colunas**
O fallback `pdfplumber` atualmente extrai a soma de TODA a página física, que pode conter múltiplos apartamentos. Para divergências residuais, o fallback acaba somando valores de outros apts junto com o alvo, retornando um número errado. A solução é passar também as coordenadas X do bloco (esquerda ou direita) para clipar o texto do pdfplumber à coluna correta.

**3. Suporte a novos modelos sem código**
Hoje adicionar modelo_e exige criar uma subclasse Python. Para administradoras com formato similar ao modelo_a ou modelo_b, seria possível cobrir 80% dos casos apenas com novas entradas em `config.yaml` (assinaturas + regex). Documentar e testar isso reduziria a dependência de desenvolvimento para onboarding de novos clientes.

### Prioridade Média

**4. Cache de extração**
Re-processar os mesmos PDFs toda vez é lento. Um cache simples (hash SHA-256 do arquivo → JSON com os dados extraídos) evitaria reprocessar PDFs que não mudaram em rodadas incrementais.

**5. Relatório de auditoria em PDF**
Além do Excel, gerar um PDF/HTML com um resumo visual: tabela de acurácia por condomínio, lista de divergências com valores esperados vs. extraídos, e % de cobertura. Facilita apresentar resultados para a cliente sem precisar abrir o Excel.

**6. Testes automatizados por modelo**
O projeto tem `tests/test_validators.py` mas sem cobertura dos parsers. Adicionar testes unitários com amostras de texto retiradas dos PDFs (linhas reais) para cada modelo garantiria que novas correções não quebrem modelos existentes — especialmente importante ao adicionar modelo_e.

**7. Processamento paralelo**
O parâmetro `--workers` já existe na CLI mas não está implementado. Usar `concurrent.futures.ProcessPoolExecutor` com `workers > 1` reduziria o tempo de processamento para lotes grandes de PDFs.

### Prioridade Baixa

**8. Banco de dados como destino de saída**
Exportar para SQLite (ou PostgreSQL) além do Excel permitiria consultas históricas: "qual apartamento mais divergiu nos últimos 6 meses?", "quais itens de despesa cresceram mais?".

**9. Detecção automática de novos layouts**
Quando um PDF não casa com nenhuma assinatura, em vez de descartar, registrar o texto da página 1 em um arquivo de quarentena para análise posterior. Facilitaria identificar novos modelos sem perder PDFs silenciosamente.
