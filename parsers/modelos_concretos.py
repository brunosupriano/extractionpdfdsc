import re
import fitz  # PyMuPDF
from parsers.modelo_a_parser import ModeloAParser
from parsers.base_parser import ParserState
from core.models import ValidationStatus
from core.utils import parse_valor_br, clean_description


class ModeloBParser(ModeloAParser):
    """Parser para Modelo B (Rateio Detalhado - coluna única).

    Linha de apartamento: "[bloco_idx] [apt_num] - [nome_morador]"
    O primeiro número é o índice de bloco, o segundo é o número do apartamento.
    """

    def parse_page(self, text: str, page_num: int, physical_page: int = None) -> None:
        self.current_page = page_num
        self.last_desc = ""

        re_bloco = re.compile(self.config['regex_bloco'])
        re_apto = re.compile(self.config['regex_apto'])
        re_item = re.compile(self.config['item_despesa'])
        re_total = re.compile(self.config['regex_total'])

        for line in text.split('\n'):
            line = line.strip()
            if not line:
                continue

            # Detectar bloco explícito (ex: "EDIFÍCIO ALFA")
            match_bloco = re_bloco.search(line)
            if match_bloco:
                if self.current_apt:
                    self.finalize_current_apt()
                self.current_bloco = match_bloco.group(1).strip()
                continue

            # Detectar apartamento: group(1) = bloco, group(2) = apt
            match_apto = re_apto.match(line)
            if match_apto:
                if self.current_apt:
                    self.finalize_current_apt()
                # group(1) é o índice de bloco (ex: "1"), group(2) é o apto (ex: "101")
                self.current_bloco = match_apto.group(1)
                num_apto = match_apto.group(2)
                self.current_apt = self._get_or_create_apt(num_apto, page_num, physical_page)
                self.transition_to(ParserState.READING_DESPESAS)
                self.last_desc = ""
                continue

            # Detectar total
            match_total = re_total.search(line)
            if match_total and self.current_apt:
                valor_total = parse_valor_br(match_total.group(1))
                if valor_total:
                    self.current_apt.total_impresso = valor_total
                self.transition_to(ParserState.READING_TOTAL)
                continue

            # Acumular despesas
            if self.state == ParserState.READING_DESPESAS and self.current_apt:
                match_item = re_item.search(line)
                if match_item:
                    raw_desc = match_item.group(2)
                    valor = parse_valor_br(match_item.group(3))
                    # Inclui negativos (isenções/descontos), exclui zero exato e ruídos curtos
                    if valor is not None and valor != 0.0 and len(raw_desc.strip()) > 2:
                        self.current_apt.despesas.append(
                            self._create_item_despesa(raw_desc, valor)
                        )


_APT_CODE_RE = re.compile(r'^\d{3,4}$')


def _build_column_map(page: fitz.Page, gap_threshold: int = 10) -> list:
    """Extrai cabeçalhos de coluna de uma página landscape do modelo_c.

    Estratégia:
    1. Encontra a primeira linha de dados (primeira palavra = código de apt 3-4 dígitos)
    2. Entre as linhas acima dela, escolhe a que tem o maior número de palavras
       com x no intervalo [100, 700] — essa é a linha de cabeçalhos de coluna
    3. Agrupa palavras cujo gap horizontal ≤ gap_threshold (10px) em um único nome

    Com gap=10px, as 16 palavras do cabeçalho do modelo_c formam exatamente 9
    grupos de colunas: SEGURO CONDOMÍNIO | CORSAN | CONSUMO GAS | CONDOMINIO |
    ENERGIA ELETRICA | CONSUMO D'ÁGUA | USO QUIOSQUE | ÁGUA E ESGOTO | ISENÇÃO

    Retorna lista de (x_center, nome_coluna) ordenada por x_center.
    """
    words = page.get_text("words")  # (x0, y0, x1, y1, word, block, line, word_no)
    if not words:
        return []

    # Agrupar palavras por linha (Y com tolerância de 3px)
    rows_by_y: dict = {}
    for w in words:
        y_key = round(w[1] / 3) * 3
        rows_by_y.setdefault(y_key, []).append(w)

    sorted_y = sorted(rows_by_y.keys())

    # Localizar Y da primeira linha de dados
    data_y = None
    for y_key in sorted_y:
        row = sorted(rows_by_y[y_key], key=lambda w: w[0])
        if row and _APT_CODE_RE.match(row[0][4]):
            data_y = y_key
            break

    if data_y is None:
        return []

    # Encontrar linha de cabeçalho: linha com o maior número de palavras
    # posicionadas no intervalo x=[100, 700] (exclui margens e área de totais)
    best_y = None
    best_count = 0
    for y_key in sorted_y:
        if y_key >= data_y:
            break
        count = sum(1 for w in rows_by_y[y_key] if 100 <= w[0] <= 700)
        if count > best_count:
            best_count = count
            best_y = y_key

    if best_y is None or best_count < 3:
        return []

    header_words_row = sorted(rows_by_y[best_y], key=lambda w: w[0])

    # Agrupar palavras cujo gap horizontal ≤ gap_threshold em um nome de coluna
    columns = []
    current_group = [header_words_row[0]]
    for w in header_words_row[1:]:
        gap = w[0] - current_group[-1][2]  # x0_atual - x1_anterior
        if gap <= gap_threshold:
            current_group.append(w)
        else:
            name = " ".join(g[4] for g in current_group)
            x_center = (current_group[0][0] + current_group[-1][2]) / 2
            columns.append((x_center, name))
            current_group = [w]
    if current_group:
        name = " ".join(g[4] for g in current_group)
        x_center = (current_group[0][0] + current_group[-1][2]) / 2
        columns.append((x_center, name))

    return columns


class ModeloCParser(ModeloAParser):
    """Parser para o Modelo C (Crédito Real Imóveis).

    Suporta dois formatos, detectados automaticamente pelo conteúdo:

    LISTA — "RESUMO DE DOC'S DE CONDOMÍNIO" (ex: RESIDENCIAL POEMA)
      Estrutura por apartamento:
        {apt} {nome} AP RESIDENCIAL {fracao}          ← cabeçalho do apt
        {taxa} {desc} AP {apt} ({tipo}) {compl} {valor} ← cobrança
        Total do Boleto {total} ...                   ← finaliza apt

    TABELA — Layout landscape com uma linha por apt e colunas de encargo
      (ex: RESIDENCIAL PORTO ONIX — mantido por compatibilidade).
    """

    # Padrão monetário: exige exatamente 2 casas decimais
    _RE_VALOR = re.compile(r'-?\d{1,3}(?:\.\d{3})*,\d{2}(?!\d)')

    # --- Formato lista ---
    # Cabeçalho de apt: "101 NOME AP RESIDENCIAL 0,00392610"
    _RE_APT_HEADER = re.compile(
        r'^\s*(\d{3,4})\s+\S.*\bAP\s+(?:RESIDENCIAL|COMERCIAL|SALA|LOJA|GARAGEM)\b',
        re.IGNORECASE,
    )
    # Referência do apt dentro de uma linha de cobrança: "AP 101 (C)"
    _RE_APT_REF = re.compile(r'\bAP\s+\d{2,4}\s+\([A-Z]\)', re.IGNORECASE)
    # Descrição entre o código de taxa e a referência do apt
    _RE_CHARGE_DESC = re.compile(
        r'^\s*\d+\s+(.*?)\s+AP\s+\d{2,4}\s+\([A-Z]\)', re.IGNORECASE
    )
    # Total do boleto: "Total do Boleto 482,36 ..."
    _RE_TOTAL_BOLETO = re.compile(r'Total\s+do\s+Boleto\s+([\d.,]+)', re.IGNORECASE)
    # Linhas de cabeçalho/rodapé a ignorar no formato lista
    _RE_SKIP_LIST = re.compile(
        r'^\s*(?:'
        r'Cr[eé]dito\s+Real'
        r'|RESUMO\s+DE\s+DOC'
        r'|Emiss[aã]o:'
        r'|Condom[ií]nio:'
        r'|Taxa\s+Descri'
        r'|Economia\(s\)'
        r'|\d{2}/\d{2}/\d{4}'   # rodapé com data
        r')',
        re.IGNORECASE,
    )

    # --- Formato tabela ---
    # Linha que começa com código de economia (3-4 dígitos) seguido de espaço
    _RE_APT_ROW = re.compile(r'^\s*(\d{3,4})\s+')

    # ------------------------------------------------------------------ #
    #  Detecção de formato e dispatch                                      #
    # ------------------------------------------------------------------ #

    def parse_page(self, text: str, page_num: int, physical_page: int = None) -> None:
        self.current_page = page_num
        if self._RE_TOTAL_BOLETO.search(text) or 'Economia(s):' in text:
            self._parse_page_list_format(text, page_num, physical_page)
        else:
            self._parse_page_table_format(text, page_num, physical_page)

    # ------------------------------------------------------------------ #
    #  Formato LISTA                                                       #
    # ------------------------------------------------------------------ #

    def _parse_page_list_format(self, text: str, page_num: int,
                                physical_page: int = None) -> None:
        """Parseia o formato de lista Crédito Real (RESUMO DE DOC'S DE CONDOMÍNIO).

        O número do apartamento vem da linha de cabeçalho (ex: "101 NOME AP RESIDENCIAL").
        Os números que iniciam linhas de cobrança (ex: 106, 120, 121) são CÓDIGOS DE TAXA,
        não números de apartamento.
        """
        for line in text.split('\n'):
            line = line.strip()
            if not line:
                continue
            if self._RE_SKIP_LIST.match(line):
                continue

            # Total do boleto → grava total e finaliza apt
            m_total = self._RE_TOTAL_BOLETO.search(line)
            if m_total:
                if self.current_apt:
                    valor_total = parse_valor_br(m_total.group(1))
                    if valor_total:
                        self.current_apt.total_impresso = valor_total
                    self.finalize_current_apt()
                continue

            # Cabeçalho de apartamento: 3-4 dígitos + nome + "AP RESIDENCIAL"
            m_header = self._RE_APT_HEADER.match(line)
            if m_header:
                if self.current_apt:
                    self.finalize_current_apt()
                num_apto = m_header.group(1)
                self.current_apt = self._get_or_create_apt(
                    num_apto, page_num, physical_page
                )
                continue

            # Linha de cobrança: contém "AP {digits} ({letter})" + valor monetário
            if self._RE_APT_REF.search(line) and self.current_apt:
                vals = self._RE_VALOR.findall(line)
                if not vals:
                    continue
                valor = parse_valor_br(vals[-1])
                if valor is None or valor == 0.0:
                    continue

                # Descrição: texto entre o código de taxa e "AP {apt} ({tipo})"
                m_desc = self._RE_CHARGE_DESC.match(line)
                if m_desc:
                    raw_desc = re.sub(r'\s*[-–]\s*$', '', m_desc.group(1)).strip()
                else:
                    raw_desc = ""

                if raw_desc:
                    self.current_apt.despesas.append(
                        self._create_item_despesa(raw_desc, valor)
                    )

    # ------------------------------------------------------------------ #
    #  Formato TABELA (landscape, uma linha por apt)                       #
    # ------------------------------------------------------------------ #

    def _parse_page_table_format(self, text: str, page_num: int,
                                 physical_page: int = None) -> None:
        """Parseia o formato tabela landscape (coluna por tipo de encargo)."""
        re_bloco = re.compile(self.config['regex_bloco'])
        re_separator = re.compile(r'^[-]{5,}')
        in_subsection = False
        subsection_name = ""

        col_map = self._get_column_map(physical_page)

        for line in text.split('\n'):
            line = line.strip()
            if not line:
                continue

            if re_separator.match(line):
                if self.current_apt:
                    self.finalize_current_apt()
                in_subsection = True
                subsection_name = ""
                continue

            m_bloco = re_bloco.search(line)
            if m_bloco:
                if self.current_apt:
                    self.finalize_current_apt()
                self.current_bloco = m_bloco.group(1)
                in_subsection = False
                subsection_name = ""
                continue

            if re.match(r'^\s*(?:Economia|Tipo|Bloco|Competência|Emissão|Vencimento'
                        r'|Pág\.|RESUMO|Total\s+Bloco)', line, re.IGNORECASE):
                continue

            if in_subsection and not subsection_name and not self._RE_APT_ROW.match(line):
                if not self._RE_VALOR.search(line):
                    subsection_name = line.strip()
                continue

            m_apt = self._RE_APT_ROW.match(line)
            if not m_apt:
                continue

            num_apto = m_apt.group(1)

            if self.current_apt and self.current_apt.apartamento != num_apto:
                self.finalize_current_apt()

            self.current_apt = self._get_or_create_apt(num_apto, page_num, physical_page)

            if col_map and not in_subsection:
                self._parse_line_with_coords(num_apto, physical_page, in_subsection, col_map)
            else:
                self._parse_line_text_only(line, in_subsection, subsection_name)

            self.finalize_current_apt()

    # ------------------------------------------------------------------ #
    #  Helpers compartilhados (usados pelo formato tabela)                 #
    # ------------------------------------------------------------------ #

    def _get_column_map(self, physical_page: int) -> list:
        """Retorna o mapa de colunas: lista de (índice_ou_x, nome_coluna).

        Prioridade:
        1. Se 'colunas_despesa' estiver definido no config, usa diretamente —
           evita ambiguidade geométrica do layout do PDF.
        2. Caso contrário, tenta detecção dinâmica via coordenadas do PDF.
        """
        if 'colunas_despesa' in self.config:
            return [(i, name) for i, name in enumerate(self.config['colunas_despesa'])]

        if not self.arquivo_origem or not physical_page:
            return []
        try:
            doc = fitz.open(self.arquivo_origem)
            if physical_page < 1 or physical_page > len(doc):
                doc.close()
                return []
            page = doc[physical_page - 1]
            col_map = _build_column_map(page)
            doc.close()
            return col_map
        except Exception:
            return []

    def _get_apt_value_positions(self, num_apto: str, physical_page: int) -> list:
        """Retorna lista de (x_center, value_str) para a linha do apartamento na página."""
        if not self.arquivo_origem or not physical_page:
            return []
        try:
            doc = fitz.open(self.arquivo_origem)
            if physical_page < 1 or physical_page > len(doc):
                doc.close()
                return []
            page = doc[physical_page - 1]
            words = page.get_text("words")
            doc.close()
        except Exception:
            return []

        lines_by_y: dict = {}
        for w in words:
            y_key = round(w[1] / 3) * 3
            lines_by_y.setdefault(y_key, []).append(w)

        apt_re = re.compile(r'^\s*' + re.escape(num_apto) + r'\s*$')
        val_re = self._RE_VALOR

        for y_key in sorted(lines_by_y.keys()):
            row_words = sorted(lines_by_y[y_key], key=lambda w: w[0])
            if not row_words:
                continue
            if not apt_re.match(row_words[0][4]):
                continue
            result = []
            for w in row_words:
                token = w[4].replace('\xa0', '')
                x_center = (w[0] + w[2]) / 2
                if val_re.fullmatch(token):
                    result.append((x_center, token))
                else:
                    for m in val_re.findall(token):
                        result.append((x_center, m))
            return result

        return []

    def _parse_line_with_coords(self, num_apto: str, physical_page: int,
                                in_subsection: bool, col_map: list) -> None:
        """Extrai despesas mapeando valores ao nome da coluna por posição ordinal."""
        positions = self._get_apt_value_positions(num_apto, physical_page)
        if not positions:
            return

        if not in_subsection and self.current_apt:
            total = parse_valor_br(positions[-1][1])
            if total and total > 0:
                self.current_apt.total_impresso = total

        for i, (x_center, v_str) in enumerate(positions[:-1]):
            v = parse_valor_br(v_str)
            if v is not None and v != 0.0 and self.current_apt:
                desc = col_map[i][1] if i < len(col_map) else f"Encargo {i + 1}"
                self.current_apt.despesas.append(
                    self._create_item_despesa(desc, v)
                )

    def _parse_line_text_only(self, line: str, in_subsection: bool,
                              subsection_name: str = "") -> None:
        """Fallback: extrai valores da linha de texto sem coordenadas."""
        valores = self._RE_VALOR.findall(line)
        if not valores:
            return

        if not in_subsection and self.current_apt:
            total = parse_valor_br(valores[-1])
            if total and total > 0:
                self.current_apt.total_impresso = total

        for i, v_str in enumerate(valores[:-1]):
            v = parse_valor_br(v_str)
            if v is not None and v != 0.0 and self.current_apt:
                desc = subsection_name if subsection_name else f"Encargo {i + 1}"
                self.current_apt.despesas.append(
                    self._create_item_despesa(desc, v)
                )


class ModeloDParser(ModeloAParser):
    """Implementação concreta para o Modelo D."""
    pass
