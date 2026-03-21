from __future__ import annotations
from pydantic import BaseModel, Field
from enum import Enum
from typing import List, Optional

class ExtractionLayer(str, Enum):
    PYMUPDF = "pymupdf"       # extração geométrica via PyMuPDF (camada primária)
    PDFPLUMBER = "pdfplumber" # fallback via pdfplumber (tabelas/coordenadas)
    HYBRID = "hibrido"        # mistura: alguns apts via fallback, outros via PyMuPDF

class ValidationStatus(str, Enum):
    OK = "OK"
    DIVERGENTE = "DIVERGENTE"
    SEM_TOTAL = "SEM_TOTAL"

class ItemDespesa(BaseModel):
    descricao: str
    valor: float

class DadosApartamento(BaseModel):
    apartamento: str
    despesas: List[ItemDespesa] = Field(default_factory=list)
    total_impresso: Optional[float] = None
    soma_calculada: float = 0.0
    taxa_assertividade: float = 0.0
    status_validacao: ValidationStatus = ValidationStatus.SEM_TOTAL
    pagina_origem: int = 1

    def calcular_validacao(self, tolerancia: float = 0.5) -> None:
        """Realiza o cálculo da soma e validação contra o total impresso."""
        self.soma_calculada = sum(item.valor for item in self.despesas)
        if self.total_impresso is not None and self.total_impresso > 0:
            self.taxa_assertividade = (self.soma_calculada / self.total_impresso) * 100
            diff = abs(self.taxa_assertividade - 100)
            self.status_validacao = ValidationStatus.OK if diff <= tolerancia else ValidationStatus.DIVERGENTE
        else:
            self.status_validacao = ValidationStatus.SEM_TOTAL
            self.taxa_assertividade = 0.0

class DadosBloco(BaseModel):
    bloco: str
    apartamentos: List[DadosApartamento] = Field(default_factory=list)

class DadosCondominio(BaseModel):
    arquivo_origem: str
    modelo_pdf: str
    condominio: str
    blocos: List[DadosBloco] = Field(default_factory=list)
    paginas_processadas: int = 0
    camada_extracao: ExtractionLayer = ExtractionLayer.PYMUPDF
