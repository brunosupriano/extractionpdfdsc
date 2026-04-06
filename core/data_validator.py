import pdfplumber
from loguru import logger
from core.models import DadosCondominio, ValidationStatus, ExtractionLayer
from typing import Dict, Any

class DataValidator:
    """Valida a consistência financeira e coordena o fallback se necessário."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        tolerancia = config.get('validacao', {}).get('tolerancia_percentual', 0.5)
        self.tolerancia = tolerancia / 100 # Converte % para fração

    def _calcular_divergencia(self, soma: float, total: float) -> float:
        if total == 0: return 0.0
        return abs(soma - total) / total

    def validate_and_fallback(self,
                             dados: DadosCondominio,
                             pdf_path: str,
                             parser_instance: Any) -> DadosCondominio:
        """Percorre os dados extraídos e aplica fallback se necessário."""
        for bloco in dados.blocos:
            for apt in bloco.apartamentos:

                if apt.total_impresso is None:
                    apt.status_validacao = ValidationStatus.SEM_TOTAL
                    continue

                apt.soma_calculada = sum(i.valor for i in apt.despesas)
                if apt.total_impresso > 0:
                    apt.taxa_assertividade = (apt.soma_calculada / apt.total_impresso) * 100
                div = self._calcular_divergencia(apt.soma_calculada, apt.total_impresso)

                if div <= self.tolerancia:
                    apt.status_validacao = ValidationStatus.OK
                    continue

                # DIVERGENTE — loga breakdown completo para diagnóstico sem LLM
                diferenca = apt.total_impresso - apt.soma_calculada
                logger.warning(
                    f"Divergência {div:.1%} | Apto {apt.apartamento} (Pág {apt.pagina_origem}) | "
                    f"Total PDF: R${apt.total_impresso:.2f} | "
                    f"Soma extraída: R${apt.soma_calculada:.2f} | "
                    f"Diferença: R${diferenca:.2f}"
                )
                logger.warning(
                    f"  Itens capturados ({len(apt.despesas)}): "
                    + " | ".join(
                        f"{i.descricao[:20]}={i.valor:.2f}"
                        for i in apt.despesas
                    )
                )
                logger.warning(f"  Acionando FALLBACK pdfplumber para {apt.apartamento}...")

                recalculado = self._fallback_pdfplumber(pdf_path, [apt.pagina_origem], apt.apartamento)

                if recalculado is not None:
                    nova_div = self._calcular_divergencia(recalculado, apt.total_impresso)
                    if nova_div <= self.tolerancia:
                        apt.soma_calculada = recalculado
                        apt.status_validacao = ValidationStatus.OK
                        logger.success(f"Fallback resolveu {apt.apartamento}!")
                        dados.camada_extracao = ExtractionLayer.HYBRID
                        continue

                apt.status_validacao = ValidationStatus.DIVERGENTE
                logger.error(
                    f"Fallback falhou para {apt.apartamento}. "
                    f"Soma: R${apt.soma_calculada:.2f} | Total PDF: R${apt.total_impresso:.2f} | "
                    f"Falta: R${apt.total_impresso - apt.soma_calculada:.2f} — "
                    f"verifique regex_apto/item_despesa no config.yaml para este PDF."
                )

        return dados

    def _fallback_pdfplumber(self, pdf_path: str, paginas: list[int], apt_id: str) -> float | None:
        """Extrai a soma dos valores usando pdfplumber de forma independente."""
        from core.utils import parse_valor_br
        total_soma = 0.0
        encontrou = False

        try:
            with pdfplumber.open(pdf_path) as pdf:
                for num_pag in paginas:
                    if num_pag > len(pdf.pages): continue
                    page = pdf.pages[num_pag - 1]

                    # Tenta tabelas estruturadas
                    tabelas = page.extract_tables()
                    for tabela in tabelas:
                        for linha in tabela:
                            if not linha: continue
                            valores = [c for c in linha if c and c.strip()]
                            if len(valores) >= 2:
                                v = parse_valor_br(valores[-1])
                                if v and v > 0:
                                    total_soma += v
                                    encontrou = True

                    # Fallback para palavras isoladas se não achou nada
                    if not encontrou:
                        words = page.extract_words()
                        for word in words:
                            v = parse_valor_br(word['text'])
                            if v and v > 0:
                                total_soma += v
                                encontrou = True
        except Exception as e:
            logger.error(f"Erro no fallback pdfplumber para {apt_id}: {e}")
            return None

        return total_soma if encontrou else None
