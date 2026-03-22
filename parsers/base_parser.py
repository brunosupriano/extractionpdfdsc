from abc import ABC, abstractmethod
from enum import Enum
from typing import List, Optional, Any, Dict
from models import ItemDespesa, DadosApartamento, DadosBloco, DadosCondominio
from utils import clean_text
import re
from loguru import logger

class ParserState(Enum):
    IDLE = "IDLE"
    READING_BLOCO = "READING_BLOCO"
    READING_APT = "READING_APT"
    READING_DESPESAS = "READING_DESPESAS"
    READING_TOTAL = "READING_TOTAL"

class BasePDFParser(ABC):
    """Classe base abstrata para todos os parsers de PDF.
    Implementa a Máquina de Estados para lidar com quebras de página.
    """
    
    def __init__(self, config: Dict[str, Any], arquivo_origem: str, modelo_pdf: str):
        self.config = config
        self.arquivo_origem = arquivo_origem
        self.modelo_pdf = modelo_pdf
        self.state = ParserState.IDLE
        
        # Contexto atual
        self.current_bloco: Optional[str] = None
        self.current_apt: Optional[DadosApartamento] = None
        self.condominio_data = DadosCondominio(
            arquivo_origem=arquivo_origem,
            modelo_pdf=modelo_pdf,
            condominio=config.get('nome_condominio', 'Não Identificado')
        )
        self.current_page = 1

    @abstractmethod
    def parse_page(self, text: str, page_num: int, physical_page: Optional[int] = None) -> None:
        """Processa o texto de uma página específica.

        Args:
            text: Texto extraído da página (ou coluna virtual).
            page_num: Número da página/coluna virtual (1-based).
            physical_page: Página física real do PDF (usada pelo fallback pdfplumber).
        """
        pass

    def get_result(self) -> DadosCondominio:
        """Retorna os dados consolidados do condomínio."""
        return self.condominio_data

    def _get_or_create_bloco(self, nome_bloco: str) -> DadosBloco:
        """Busca um bloco existente ou cria um novo."""
        nome_bloco = clean_text(nome_bloco or "ÚNICO")
        for bloco in self.condominio_data.blocos:
            if bloco.bloco == nome_bloco:
                return bloco
        
        novo_bloco = DadosBloco(bloco=nome_bloco)
        self.condominio_data.blocos.append(novo_bloco)
        return novo_bloco

    def _get_or_create_apt(self, num_apto: str, page_num: int, physical_page: Optional[int] = None) -> DadosApartamento:
        """Recupera apto existente para cumulatividade ou cria um novo.
        Essencial para lidar com quebras de página.
        physical_page: página física do PDF (não a virtual), usada pelo fallback pdfplumber.
        """
        bloco_obj = self._get_or_create_bloco(self.current_bloco)
        for apt in bloco_obj.apartamentos:
            if apt.apartamento == num_apto:
                return apt

        pagina = physical_page if physical_page is not None else page_num
        novo_apt = DadosApartamento(apartamento=num_apto, pagina_origem=pagina)
        bloco_obj.apartamentos.append(novo_apt)
        return novo_apt

    def transition_to(self, new_state: ParserState):
        """Gerencia as transições de estado."""
        self.state = new_state

    def finalize_current_apt(self):
        """Limpa o buffer do apartamento atual sem removê-lo do bloco."""
        self.current_apt = None
        self.transition_to(ParserState.READING_BLOCO)
