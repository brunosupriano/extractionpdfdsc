from parsers.base_parser import BasePDFParser, ParserState
from models import ItemDespesa
from utils import parse_valor_br, clean_text, clean_description
import re
from typing import Dict, Any

class ModeloAParser(BasePDFParser):
    """Implementação para Modelo A calibrada via diagnóstico geométrico."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_desc: str = ""
        # Guarda o subtotal sem multa (linha numérica isolada antes de "Com multa:")
        # para poder calcular a multa/juros como item derivado.
        self.subtotal_candidate: float = 0.0

    def parse_page(self, text: str, page_num: int, physical_page: int = None) -> None:
        self.current_page = page_num
        # Reseta last_desc por página: evita que cabeçalhos/rodapés contaminem
        # itens do apartamento seguinte. subtotal_candidate NÃO é resetado aqui
        # porque o subtotal e o "Com multa:" podem estar em virtual pages diferentes.
        # Ele é resetado quando um novo apartamento começa (abaixo).
        self.last_desc = ""
        lines = text.split('\n')

        re_bloco = re.compile(self.config['regex_bloco'])
        re_apto = re.compile(self.config['regex_apto'])
        re_item = re.compile(self.config['item_despesa'])
        re_total = re.compile(self.config['regex_total'])

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 1. Detectar Bloco e Apto
            match_apto = re_apto.search(line)
            if match_apto:
                if self.current_apt:
                    self.finalize_current_apt()
                num_apto = match_apto.group(1)

                match_bloco = re_bloco.search(line)
                if match_bloco:
                    self.current_bloco = match_bloco.group(1)

                self.current_apt = self._get_or_create_apt(num_apto, page_num, physical_page)
                self.transition_to(ParserState.READING_DESPESAS)
                self.last_desc = ""
                self.subtotal_candidate = 0.0
                continue

            # 2. Detectar Total (Com multa:)
            match_total = re_total.search(line)
            if match_total and self.current_apt:
                # Usa o subtotal (sem multa) como total de referência.
                # O TOTAIS do PDF soma os encargos base — sem incluir multa/juros
                # de mora, que é uma taxa variável por inadimplência e não faz
                # parte do orçamento oficial do condomínio.
                # Fallback: se não há subtotal capturado, usa o valor "Com multa".
                if self.subtotal_candidate > 0:
                    self.current_apt.total_impresso = self.subtotal_candidate
                else:
                    valor_total = parse_valor_br(match_total.group(1))
                    if valor_total:
                        self.current_apt.total_impresso = valor_total
                self.subtotal_candidate = 0.0
                # Para de acumular itens após o total (evita TOTAIS, rodapés, etc.)
                self.transition_to(ParserState.READING_TOTAL)
                continue

            # 3. Lógica de Itens
            if self.state == ParserState.READING_DESPESAS and self.current_apt:
                match_item = re_item.search(line)
                if match_item:
                    # Formato: [Código] Descrição Valor
                    desc = clean_description(match_item.group(2))
                    valor = parse_valor_br(match_item.group(3))

                    if valor and valor > 0:
                        # Ignora ruídos que não são itens de despesa reais
                        if len(desc) > 3 and not any(x in desc.upper() for x in ["CASA", "BL.", "MULTA"]):
                            self.current_apt.despesas.append(ItemDespesa(descricao=desc, valor=valor))
                else:
                    # Valor numérico isolado (sem match de item) = candidato a subtotal.
                    # Itens em modelo_a são sempre de linha única, então não há
                    # necessidade de buffer de descrição (last_desc). Qualquer valor
                    # isolado é tratado como o subtotal antes de "Com multa:".
                    v = parse_valor_br(line)
                    if v and v > 0:
                        self.subtotal_candidate = v
