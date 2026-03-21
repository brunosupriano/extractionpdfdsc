import re
from parsers.modelo_a_parser import ModeloAParser
from parsers.base_parser import ParserState
from models import ItemDespesa, ValidationStatus
from utils import parse_valor_br


class ModeloBParser(ModeloAParser):
    """Implementação concreta para o Modelo B (Rateio Detalhado - coluna única)."""
    pass


class ModeloCParser(ModeloAParser):
    """Parser para o Modelo C (Imobiliar - tabela landscape).

    Cada linha da tabela representa um apartamento completo:
      ECONOMIA | tipo | coluna1 | ... | Total DOC

    O último valor numérico da linha é o Total DOC (total_impresso).
    Os valores intermediários são registrados como despesas genéricas.
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

        for line in text.split('\n'):
            line = line.strip()
            if not line:
                continue

            # Separador: marca início de rodapé/subseção (FUNDO RESERVA, ÁGUA, etc.)
            if re_separator.match(line):
                if self.current_apt:
                    self.finalize_current_apt()
                in_subsection = True
                continue

            # Cabeçalho de bloco (ex: "Bloco: BLOCO 01") — reseta subseção
            m_bloco = re_bloco.search(line)
            if m_bloco:
                if self.current_apt:
                    self.finalize_current_apt()
                self.current_bloco = m_bloco.group(1)
                in_subsection = False
                continue

            # Linhas de cabeçalho de tabela / rodapé (ignorar)
            if re.match(r'^\s*(?:Economia|Tipo|Bloco|Competência|Emissão|Vencimento'
                        r'|Pág\.|RESUMO|Total\s+Bloco)', line, re.IGNORECASE):
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

            # Extrair todos os valores monetários da linha
            valores = self._RE_VALOR.findall(line)
            if not valores:
                self.finalize_current_apt()
                continue

            # Último valor = Total DOC (total_impresso).
            # Em subseções (FUNDO RESERVA, etc.) o total_impresso já foi definido
            # na seção principal — não sobrescrever.
            if not in_subsection:
                total = parse_valor_br(valores[-1])
                if total and total > 0:
                    self.current_apt.total_impresso = total

            # Valores intermediários = despesas individuais
            for i, v_str in enumerate(valores[:-1]):
                v = parse_valor_br(v_str)
                if v is not None and v != 0.0:
                    self.current_apt.despesas.append(
                        ItemDespesa(descricao=f"Encargo {i + 1}", valor=v)
                    )

            # Cada linha de tabela é um registro completo
            self.finalize_current_apt()


class ModeloDParser(ModeloAParser):
    """Implementação concreta para o Modelo D."""
    pass
