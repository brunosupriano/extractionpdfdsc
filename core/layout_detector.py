import re
import yaml
import fitz # PyMuPDF
from typing import Dict, Any, Optional, Type
from loguru import logger
from parsers.base_parser import BasePDFParser
from rapidfuzz import process, fuzz

class ParserFactory:
    """Fábrica de parsers que identifica o layout do PDF e instancia o parser correto."""

    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)

        self.layout_configs = self.config.get('layouts', {})
        self._parsers_registry: Dict[str, Type[BasePDFParser]] = {}

    def register_parser(self, layout_id: str, parser_class: Type[BasePDFParser]):
        """Registra uma subclasse concreta de BasePDFParser."""
        self._parsers_registry[layout_id] = parser_class

    def detect_layout(self, pdf_path: str) -> Optional[str]:
        """Detecta o layout do PDF lendo a primeira página com PyMuPDF.

        Utiliza heurísticas de assinaturas e correspondência fuzzy para robustez.
        """
        try:
            doc = fitz.open(pdf_path)
            if doc.page_count == 0:
                logger.error(f"PDF vazio: {pdf_path}")
                return None

            # Extrai texto da página 1 (metadados e assinaturas costumam estar aqui)
            page1_text = doc[0].get_text().upper()
            doc.close()

            # Heurística 1: Assinaturas exatas e parciais
            for layout_id, layout_cfg in self.layout_configs.items():
                signatures = [s.upper() for s in layout_cfg.get('assinaturas', [])]
                for sig in signatures:
                    if sig in page1_text:
                        logger.info(f"Layout detectado via assinatura: {layout_id}")
                        return layout_id

            # Heurística 2: Fuzzy Matching (Caso de OCR imperfeito)
            # Tenta encontrar a melhor correspondência para as assinaturas
            all_sigs = []
            sig_to_layout = {}
            for layout_id, layout_cfg in self.layout_configs.items():
                for sig in layout_cfg.get('assinaturas', []):
                    all_sigs.append(sig.upper())
                    sig_to_layout[sig.upper()] = layout_id

            if all_sigs:
                best_match = process.extractOne(page1_text, all_sigs, scorer=fuzz.partial_ratio)
                if best_match and best_match[1] > 85: # Threshold de 85% de confiança
                    detected = sig_to_layout[best_match[0]]
                    logger.info(f"Layout detectado via fuzzy matching ({best_match[1]}%): {detected}")
                    return detected

            logger.warning(f"Não foi possível detectar o layout para {pdf_path}")
            return None

        except Exception as e:
            logger.error(f"Erro na detecção de layout: {e}")
            return None

    def get_parser(self, layout_id: str, arquivo_origem: str) -> Optional[BasePDFParser]:
        """Retorna uma instância do parser correto para o layout."""
        parser_cls = self._parsers_registry.get(layout_id)
        if not parser_cls:
            logger.error(f"Parser não registrado para o layout: {layout_id}")
            return None

        layout_cfg = self.layout_configs.get(layout_id)
        return parser_cls(layout_cfg, arquivo_origem, layout_id)
