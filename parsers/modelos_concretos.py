import re
import fitz  # PyMuPDF
from parsers.modelo_a_parser import ModeloAParser
from parsers.base_parser import ParserState
from models import ItemDespesa, ValidationStatus
from utils import parse_valor_br, clean_description


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
                    desc = clean_description(match_item.group(2))
                    valor = parse_valor_br(match_item.group(3))
                    if valor and valor > 0 and len(desc) > 2:
                        self.current_apt.despesas.append(ItemDespesa(descricao=desc, valor=valor))


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
    """Parser para o Modelo C (Imobiliar - tabela landscape).

    Cada linha da tabela representa um apartamento completo:
      ECONOMIA | tipo | coluna1 | ... | Total DOC

    O último valor numérico da linha é o Total DOC (total_impresso).
    Os valores intermediários são mapeados aos cabeçalhos de coluna via
    coordenadas X extraídas diretamente do PDF.
    """

    # Padrão monetário (positivo ou negativo) com lookahead para não capturar
    # partes de volumes (ex: 3,506 m3)
    _RE_VALOR = re.compile(r'-?\d{1,3}(?:\.\d{3})*,\d{2}(?!\d)')
    # Linha que começa com código de economia (3-4 dígitos) seguido de espaço
    # (exige espaço para evitar falso positivo em valores como "292,78")
    _RE_APT_ROW = re.compile(r'^\s*(\d{3,4})\s+')

    def parse_page(self, text: str, page_num: int, physical_page: int = None) -> None:
        self.current_page = page_num
        re_bloco = re.compile(self.config['regex_bloco'])
        # Detecta linha de separação de seções (sequência de traços/hifens)
        re_separator = re.compile(r'^[-]{5,}')
        in_subsection = False
        subsection_name = ""

        # Tentar construir mapa de colunas via coordenadas do PDF
        col_map = self._get_column_map(physical_page)

        for line in text.split('\n'):
            line = line.strip()
            if not line:
                continue

            # Separador: marca início de rodapé/subseção (FUNDO RESERVA, ÁGUA, etc.)
            if re_separator.match(line):
                if self.current_apt:
                    self.finalize_current_apt()
                in_subsection = True
                subsection_name = ""  # será preenchido pela próxima linha de cabeçalho
                continue

            # Cabeçalho de bloco (ex: "Bloco: BLOCO 01") — reseta subseção
            m_bloco = re_bloco.search(line)
            if m_bloco:
                if self.current_apt:
                    self.finalize_current_apt()
                self.current_bloco = m_bloco.group(1)
                in_subsection = False
                subsection_name = ""
                continue

            # Linhas de cabeçalho de tabela / rodapé
            if re.match(r'^\s*(?:Economia|Tipo|Bloco|Competência|Emissão|Vencimento'
                        r'|Pág\.|RESUMO|Total\s+Bloco)', line, re.IGNORECASE):
                continue

            # Nome da subseção (ex: "FUNDO RESERVA", "ÁGUA") — linha não numérica
            # após o separador, antes das linhas de dados
            if in_subsection and not subsection_name and not self._RE_APT_ROW.match(line):
                if not self._RE_VALOR.search(line):
                    subsection_name = line.strip()
                continue

            # Linha de dado: começa com código de economia seguido de espaço
            m_apt = self._RE_APT_ROW.match(line)
            if not m_apt:
                continue

            num_apto = m_apt.group(1)

            # Finalizar apto anterior se diferente
            if self.current_apt and self.current_apt.apartamento != num_apto:
                self.finalize_current_apt()

            self.current_apt = self._get_or_create_apt(num_apto, page_num, physical_page)

            # Seção principal: usa coordenadas para nomear colunas.
            # Subseção (FUNDO RESERVA, etc.): usa texto simples — as linhas
            # de subseção têm estrutura diferente e as coords retornariam
            # os dados da seção principal novamente.
            if col_map and not in_subsection:
                self._parse_line_with_coords(num_apto, physical_page, in_subsection, col_map)
            else:
                self._parse_line_text_only(line, in_subsection, subsection_name)

            # Cada linha de tabela é um registro completo
            self.finalize_current_apt()

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

        # Encontrar a linha do apartamento: começa com num_apto como primeira palavra
        # Agrupar palavras por linha (y0 com tolerância de 3px)
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
            # Primeira palavra da linha deve ser o código do apartamento
            if not apt_re.match(row_words[0][4]):
                continue
            # Extrair valores monetários com seus centros X.
            # Tenta fullmatch primeiro; se falhar, usa findall para capturar
            # valores embutidos em tokens compostos (ex: "2,79(06/06)").
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
        """Extrai despesas mapeando valores ao nome da coluna por posição ordinal.

        O col_map é uma lista ordenada de (x_center, nome) que corresponde
        posicionalmente aos valores monetários da linha de dados. O i-ésimo
        valor (excluindo o Total DOC final) mapeia ao col_map[i].
        """
        positions = self._get_apt_value_positions(num_apto, physical_page)
        if not positions:
            return

        # Último valor = Total DOC
        if not in_subsection and self.current_apt:
            total = parse_valor_br(positions[-1][1])
            if total and total > 0:
                self.current_apt.total_impresso = total

        # Valores intermediários → descrição por posição ordinal no col_map
        for i, (x_center, v_str) in enumerate(positions[:-1]):
            v = parse_valor_br(v_str)
            if v is not None and v != 0.0 and self.current_apt:
                desc = col_map[i][1] if i < len(col_map) else f"Encargo {i + 1}"
                self.current_apt.despesas.append(ItemDespesa(descricao=desc, valor=v))

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
                self.current_apt.despesas.append(ItemDespesa(descricao=desc, valor=v))


class ModeloDParser(ModeloAParser):
    """Implementação concreta para o Modelo D."""
    pass
