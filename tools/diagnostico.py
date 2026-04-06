import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import re
import fitz
from core.utils import group_words_by_line, parse_valor_br

def diagnosticar(pdf_path: str):
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"Erro ao abrir PDF: {e}")
        return

    print(f"\n{'='*60}")
    print(f"DIAGNÓSTICO: {pdf_path}")
    print(f"Total de páginas: {len(doc)}")
    print(f"{'='*60}\n")

    # --- TESTE 1: O que está sendo extraído por coluna? ---
    print("[ TESTE 1 ] Primeiras 40 linhas da coluna esquerda (pág 1):\n")
    page = doc[0]
    mid_x = page.rect.width / 2
    rect_left = fitz.Rect(0, 0, mid_x, page.rect.height)
    words = page.get_text("words", clip=rect_left)
    lines = group_words_by_line(words, tolerance=4)
    for i, line in enumerate(lines[:40]):
        print(f"  {i:02d}: {repr(line)}")

    # --- TESTE 2: Parse monetário funciona? ---
    print("\n[ TESTE 2 ] Teste de parse monetário:")
    testes = ["1.234,56", "R$ 1.234,56", "1234,56", "12.345,00", "R$1234,56", "453,"]
    for t in testes:
        resultado = parse_valor_br(t)
        status = "OK" if resultado is not None else "FALHOU"
        print(f"  [{status}] '{t}' → {resultado}")

    # --- TESTE 3: Regex de total casa com alguma linha? ---
    print("\n[ TESTE 3 ] Buscando padrões de TOTAL nas primeiras 3 páginas:")
    padroes_total = [
        r"TOTAL\s+DO\s+APARTAMENTO",
        r"TOTAL\s+APARTAMENTO",
        r"TOTAL\s+APT",
        r"^TOTAL\b",
        r"Total\s*:",
        r"TOTAL\s*R\$",
        r"Com\s+multa\s*:",
    ]
    for page_num in range(min(3, len(doc))):
        page = doc[page_num]
        texto_completo = page.get_text("text")
        print(f"\n  Página {page_num + 1}:")
        encontrou = False
        for padrao in padroes_total:
            matches = re.findall(padrao, texto_completo, re.IGNORECASE | re.MULTILINE)
            if matches:
                print(f"    ACHOU com '{padrao}': {matches}")
                encontrou = True
        if not encontrou:
            print("    NENHUM padrão de total encontrado!")
            linhas_total = [l.strip() for l in texto_completo.split("\n")
                           if "total" in l.lower() and l.strip()]
            if linhas_total:
                print("    Linhas com 'total' (para criar regex correto):")
                for l in linhas_total[:10]:
                    print(f"      → {repr(l)}")

    # --- TESTE 4: Padrão de apartamento casa? ---
    print("\n[ TESTE 4 ] Buscando padrões de APARTAMENTO (pág 1):")
    padroes_apt = [
        r"APTO?\s+\d+",
        r"APARTAMENTO\s+\d+",
        r"CASA\s+\d+",
        r"^\d{3,4}\b",
    ]
    page = doc[0]
    texto_p1 = page.get_text("text")
    for padrao in padroes_apt:
        matches = re.findall(padrao, texto_p1, re.IGNORECASE | re.MULTILINE)
        if matches:
            print(f"  ACHOU com '{padrao}': {matches[:5]}")

    doc.close()
    print(f"\n{'='*60}")
    print("DIAGNÓSTICO CONCLUÍDO")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    pdf = sys.argv[1] if len(sys.argv) > 1 else "input_pdfs/Modelo1.pdf"
    diagnosticar(pdf)
