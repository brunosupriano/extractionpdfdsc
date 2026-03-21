# Notas Técnicas — Lições Aprendidas do Projeto

Este arquivo documenta os padrões não-óbvios, armadilhas e decisões de design descobertas durante o desenvolvimento e depuração do pipeline. É o conhecimento que **não está no README** e que seria difícil de derivar lendo o código pela primeira vez.

---

## 1. Extração de Texto (PyMuPDF)

### PDFs de 2 colunas — páginas virtuais vs. físicas

O modelo_a imprime dois apartamentos lado a lado em cada página física. O pipeline divide cada página ao meio geometricamente, gerando **2 páginas virtuais por página física**. Um PDF de 21 páginas resulta em **42 páginas virtuais**.

Isso cria uma armadilha crítica: a validação por `pdfplumber` usa **páginas físicas** (máximo 21), não virtuais. Se o número virtual (ex: 37) for passado ao pdfplumber, ele silenciosamente ignora a página (`37 > len(pdf.pages)`) e retorna `None`, fazendo todos os fallbacks falharem.

**Regra:** sempre armazenar `pagina_origem` como página física (`physical_page = (i-1) // 2 + 1`) desde o momento da extração.

### Coluna direita começa com cabeçalho de página

Cada coluna direita virtual começa com o cabeçalho da página impressa:
```
p. 2
A311 CONDOMINIO RESIDENCIAL ALTA VISTA
MARIA LUISA CARVALHO
Emitir DOCs: S
8 2025 Geração: 05/08/2025...
```
Essas linhas têm o mesmo formato que itens de despesa. O mecanismo `last_desc` (buffer de descrição de duas linhas) capturava "MARIA LUISA CARVALHO" como descrição e depois o próximo valor como despesa — criando itens falsos e dobrando a soma. A solução foi **eliminar o `last_desc` completamente** (itens de modelo_a são sempre de linha única) e resetar buffers no início de cada `parse_page`.

---

## 2. Parsing Monetário Brasileiro

### Formato
- Separador de milhar: ponto `.` → `1.234,56`
- Separador decimal: vírgula `,` → `1234,56`
- A regex correta: `(-?)(\d{1,3}(?:\.\d{3})*|\d+),(\d{2})(?!\d)`

### Armadilhas encontradas

**Volumes de água em m³:**
`"3,506 m3"` → o padrão `,\d{2}` casa com `3,50`, retornando `3.50`. O `(?!\d)` (negative lookahead) impede o match quando há mais dígitos após as duas casas decimais. Sem ele, consumo de água vira item de despesa.

**Valores negativos (créditos/isenções):**
`parse_valor_br("-306,16")` retornava `306.16` porque a regex original não capturava o sinal. Para o modelo_c (Imobiliar), o campo "Garantia Externa" é um crédito negativo que **reduz** a soma — sem o sinal negativo, a soma inflava e todos os apartamentos ficavam divergentes.

**Marcadores de rodapé em itens:**
A linha `"1370 RECUP. SALDO DEVEDOR 3/18 19,93 T"` tem um `T` no final (footnote marker do sistema da administradora). O regex `([\\d\\.,]+)$` falha porque `$` exige o valor no final absoluto. Solução: `([\\d\\.,]+)\\s*\\S?$` — permite um caractere não-whitespace opcional no fim.

---

## 3. Máquina de Estados do Parser

### Por que o estado READING_TOTAL é necessário

Após capturar `total_impresso`, o parser transita para `READING_TOTAL` e para de acumular itens. Sem isso:
- A linha do subtotal isolado (`"444,57"`) é capturada como `subtotal_candidate`
- A linha `"Com multa: 453,46"` define `total_impresso`
- Mas as linhas seguintes — cabeçalho do próximo apartamento, rodapé, linha `TOTAIS:` — continuam sendo testadas contra o regex de item e potencialmente adicionadas

### O padrão subtotal_candidate

O modelo_a imprime o subtotal sem multa numa linha isolada antes de "Com multa:":
```
444,57          ← subtotal (soma dos encargos)
Com multa: 453,46
```
O parser captura o número isolado como `subtotal_candidate`. Ao encontrar "Com multa:", calcula:
```
multa = total_impresso - subtotal_candidate   → 453,46 - 444,57 = 8,89
```
E adiciona como `ItemDespesa("Multa/Juros", 8,89)`.

**Sanidade:** `0 < multa < total * 0.15`. Se a diferença for maior que 15% do total, não é multa — é ruído ou erro de captura.

**Cross-page:** o `subtotal_candidate` **não deve ser resetado** no início de `parse_page`. O subtotal pode aparecer no final de uma página virtual e o "Com multa:" na página seguinte. Resetar entre páginas faria a multa nunca ser calculada para apartamentos na junção de páginas.

---

## 4. Modelo C (Imobiliar — tabela landscape)

### Estrutura de duas seções por página

O PDF do Imobiliar (modelo4.pdf) organiza cada página em **duas tabelas separadas por uma linha de dashes** (`---------...--------`):

```
Bloco: BLOCO 01
Economia Tipo Nosso Número  [colunas...]  Total DOC
101 AP  2,79  39,04  306,16  ...  -306,16  232,89   ← seção principal
102 AP  2,66  39,04  ...              516,55
...
-------------------------------------------------------------------------
53,58  780,80  ...                                   ← totais de coluna
FUNDO RESERVA
Economia Tipo Nosso Número  Total DOC
101 AP  15,32  Garantia Externa  232,89              ← subseção
102 AP  14,57  Garantia Externa  516,55
...
```

O `Total DOC` (último valor de cada linha) é **o mesmo em ambas as seções** — é o total geral do apartamento, não o total daquela subseção. As subseções adicionam encargos extras (fundo de reserva, água, etc.) que compõem o total.

**Comportamento correto:** acumular despesas de ambas as seções, mas **não sobrescrever `total_impresso`** na subseção (já foi definido corretamente na seção principal).

### Falso positivo no regex de apartamento

O padrão `^\s*(\d{3,4})\b` casava `"292,78"` como apartamento `"292"` porque `\b` (word boundary) ocorre entre dígito e vírgula. A solução foi exigir espaço: `^\s*(\d{3,4})\s+`. Isso garante que apenas linhas de dados reais (que têm tipo de unidade após o número, ex: `"101 AP"`) sejam reconhecidas como apartamentos.

### Nome do bloco captura texto extra

O regex `(?i)Bloco:\s*(.*?)$` com `.*?` (lazy) + `$` na prática captura todo o resto da linha, incluindo metadados de competência:
```
"Condomínio: 4148 RESIDENCIAL PORTO ONIX Bloco: BLOCO 01 Competência: 02/2026 Vencimento: 08/03/2026"
→ current_bloco = "BLOCO 01 Competência: 02/2026 Vencimento: 08/03/2026"
```
Isso é aceitável porque a chave de agrupamento continua única por bloco/mês. Mas se o sistema precisar comparar nomes de blocos entre meses, o regex deveria ser `(?i)Bloco:\s*(\S+)` para capturar apenas a identificação (`"BLOCO 01"`).

---

## 5. Modelo B (Rateio Detalhado — coluna única)

### Nunca dividir geometricamente

O modelo3.pdf é coluna única mas foi inicialmente processado com extração de 2 colunas (`dois_colunas: true`). Isso cortava cada linha de texto ao meio, misturando dados do RESUMO com dados de apartamentos e tornando todos os regex inúteis. A flag `dois_colunas: false` é **obrigatória** para qualquer PDF que não seja 2 colunas físicas.

### Capturando o número certo do apartamento

A linha de apartamento do modelo_b:
```
1  101 - CARLOS EDUARDO LOPES DE SOUZA
```
O formato é `[índice]  [número_apt] - [nome_morador]`. O regex original capturava o índice sequencial (`group(1) = "1"`) em vez do número do apartamento (`"101"`). Solução: tornar o índice não-capturante — `^\s*\d+\s+(\d+)\s+-\s+`.

---

## 6. Detecção de Layout

### Por que duas estratégias (exato + fuzzy)

O `layout_detector.py` usa primeiro matching exato de assinaturas (strings únicas de cada condomínio) e depois fuzzy matching via `rapidfuzz` com threshold de 85%. O fuzzy existe para cobrir PDFs com OCR imperfeito onde letras especiais (ã, é, ç) podem ser mal reconhecidas. Na prática, os 4 modelos atuais são identificados pelo matching exato.

### Assinaturas devem ser específicas

Uma assinatura muito genérica como "TOTAL" ou "CONDOMÍNIO" casaria com qualquer PDF. As assinaturas atuais são nomes de condomínio + nome da administradora — combinação única o suficiente para evitar falsos positivos.

---

## 7. Fallback pdfplumber

### Limitação com PDFs de 2 colunas

O fallback extrai valores de toda a **página física** — sem saber em qual coluna o apartamento está. Se a página contém 2 apartamentos (colunas esquerda e direita), o fallback soma os valores de ambos e retorna um número incorreto. Para modelo_a, o fallback geralmente falha ou retorna valor errado.

**Solução futura:** passar as coordenadas X da coluna (`clip_rect`) ao pdfplumber para restringir a extração à metade correta da página.

### O fallback soma, não lista

A lógica atual do fallback soma todos os valores numéricos da página. Isso é uma heurística grosseira — funciona quando a página tem apenas um apartamento e valores são todos despesas. Falha em páginas com múltiplos apartamentos, totais de seção ou valores fora de contexto.

---

## 8. ExtractionLayer e o Enum

O enum `ExtractionLayer` tinha um valor chamado `MARKITDOWN` como padrão, referência a uma biblioteca de extração PDF→Markdown que foi tentada inicialmente mas abandonada. O pipeline sempre usou PyMuPDF. O valor foi renomeado para `PYMUPDF` para refletir a realidade. O valor `HYBRID` indica que pelo menos um apartamento do arquivo foi resolvido pelo fallback pdfplumber.

---

## 9. Padrões Gerais de PDFs de Condomínio

Observações sobre o domínio que ajudam a interpretar o código:

- **"Com multa:"** é o total incluindo juros de atraso (multa fixa 2% + juros proporcionais). O valor antes dele é o subtotal sem multa.
- **RECUP. SALDO DEVEDOR** é um item de cobrança parcelada de saldo devedor de meses anteriores. É legítimo e deve ser incluído na soma.
- **Garantia Externa** em modelo_c é um crédito (valor negativo) que reduz o total. Apartamentos com garantia bancária têm esse campo.
- **Itens de serviço ao condômino** são marcados com `*` no final da linha do CASA (ex: `CASA 0005 - BL. S11 10/08/2025 *`). Não afeta o parsing.
- **TOTAIS:** no final do PDF lista totais por código de encargo (1 CONDOMÍNIO, 2 AGUA, etc.) e um total geral. Esses valores **não são de apartamentos** e devem ser ignorados — o estado `READING_TOTAL` protege contra isso.

---

## 10. Estrutura de Arquivos — Decisões de Design

| Decisão | Motivo |
|---|---|
| `extractors/` existe mas está vazio | Placeholder para futura separação; lógica real está em `pipeline.py` e `data_validator.py` |
| `desktop.py` usa PyPDF2 ao invés de PyMuPDF | Foi escrito antes do pipeline principal; não está integrado |
| `diagnostico.py` separado do pipeline | Ferramenta de debug para inspecionar novos PDFs antes de configurar regex |
| `config.yaml` centraliza todos os regex | Permite adicionar novos modelos sem alterar código Python |
| `parsers/__init__.py` exporta todas as classes | Permite `from parsers import ModeloAParser` ao invés de `from parsers.modelo_a_parser import ModeloAParser` |
