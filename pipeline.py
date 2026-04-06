import typer
import yaml
import os
import sys
import fitz # PyMuPDF
from typing import List, Optional
from loguru import logger
from tqdm import tqdm

from core.layout_detector import ParserFactory
from core.data_validator import DataValidator
from core.excel_exporter import ExcelExporter
from core.models import DadosCondominio
from parsers.modelo_a_parser import ModeloAParser
from parsers.modelos_concretos import ModeloBParser, ModeloCParser, ModeloDParser
from core.utils import group_words_by_line

app = typer.Typer(help="Pipeline de Extração de Dados Financeiros de Condomínios.")

def setup_logging(level: str = "INFO"):
    logger.remove()
    logger.add(sys.stderr, level=level)
    logger.add("pipeline.log", rotation="10 MB", level="DEBUG")

def extract_surgical_text(pdf_path: str) -> List[str]:
    """Extrai texto tratando colunas lado-a-lado como páginas independentes.
    Usado apenas para PDFs de duas colunas (dois_colunas: true).
    """
    doc = fitz.open(pdf_path)
    all_virtual_pages = []

    for page in doc:
        width = page.rect.width
        mid_x = width / 2

        rect_left = fitz.Rect(0, 0, mid_x, page.rect.height)
        rect_right = fitz.Rect(mid_x, 0, width, page.rect.height)

        for rect in [rect_left, rect_right]:
            words = page.get_text("words", clip=rect)
            if words:
                page_lines = group_words_by_line(words, tolerance=4)
                all_virtual_pages.append("\n".join(page_lines) + "\f")

    doc.close()
    return all_virtual_pages


def extract_full_text(pdf_path: str) -> List[str]:
    """Extrai texto de PDFs de coluna única, uma página física por vez.
    Usado para PDFs que não têm layout de duas colunas (dois_colunas: false).
    """
    doc = fitz.open(pdf_path)
    pages = []

    for page in doc:
        words = page.get_text("words")
        if words:
            page_lines = group_words_by_line(words, tolerance=4)
            pages.append("\n".join(page_lines) + "\f")

    doc.close()
    return pages

def process_single_pdf(pdf_path: str, factory: ParserFactory, validator: DataValidator) -> Optional[DadosCondominio]:
    filename = os.path.basename(pdf_path)
    logger.info(f"Iniciando processamento cirúrgico: {filename}")
    
    layout_id = factory.detect_layout(pdf_path)
    if not layout_id:
        return None
    
    parser = factory.get_parser(layout_id, pdf_path)
    if not parser:
        return None
        
    # Seleciona estratégia de extração conforme o layout do PDF
    layout_cfg = factory.layout_configs.get(layout_id, {})
    dois_colunas = layout_cfg.get('dois_colunas', True)

    if dois_colunas:
        virtual_pages = extract_surgical_text(pdf_path)
        physical_page_fn = lambda i: (i - 1) // 2 + 1
    else:
        virtual_pages = extract_full_text(pdf_path)
        physical_page_fn = lambda i: i

    for i, content in enumerate(virtual_pages, 1):
        parser.parse_page(content, i, physical_page_fn(i))
    
    parser.finalize_current_apt()
    
    dados_extraidos = parser.get_result()
    dados_extraidos.paginas_processadas = len(virtual_pages)
    
    # Validação e Fallback
    return validator.validate_and_fallback(dados_extraidos, pdf_path, parser)

@app.command()
def run(
    input_dir: str = typer.Option("./input_pdfs", help="Diretório com os PDFs de entrada."),
    output_dir: str = typer.Option("./output", help="Diretório de saída."),
    config_file: str = typer.Option("config.yaml", help="Configuração."),
    workers: int = typer.Option(1, help="Workers."),
    log_level: str = typer.Option("INFO", help="Log level.")
):
    setup_logging(log_level)
    factory = ParserFactory(config_file)
    factory.register_parser("modelo_a", ModeloAParser)
    factory.register_parser("modelo_b", ModeloBParser)
    factory.register_parser("modelo_c", ModeloCParser)
    factory.register_parser("modelo_d", ModeloDParser)
    
    validator = DataValidator(factory.config)
    pdf_files = [os.path.join(input_dir, f) for f in os.listdir(input_dir) if f.lower().endswith(".pdf")]
    
    if not pdf_files: return

    resultados = []
    for f in tqdm(pdf_files, desc="Processando PDFs"):
        res = process_single_pdf(f, factory, validator)
        if res: resultados.append(res)

    exporter = ExcelExporter(output_dir, factory.config['saida']['arquivo'])
    exporter.export(resultados)
    logger.success("Processamento concluído!")

if __name__ == "__main__":
    app()
