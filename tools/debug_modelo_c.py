"""Diagnóstico do texto bruto extraído do modelo_c (tabela landscape).

Uso:
    python tools/debug_modelo_c.py input_pdfs/modelo3.pdf
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import re
import fitz
from core.utils import group_words_by_line

_RE_VALOR = re.compile(r'-?\d{1,3}(?:\.\d{3})*,\d{2}(?!\d)')
_RE_APT   = re.compile(r'^\s*(\d{3,4})\s+')

def run(pdf_path: str):
    doc = fitz.open(pdf_path)
    print(f"\nPDF: {pdf_path}  |  Páginas: {len(doc)}\n")

    for pg_idx, page in enumerate(doc):
        words = page.get_text("words")
        lines = group_words_by_line(words, tolerance=4)

        print(f"{'='*70}")
        print(f"PÁGINA {pg_idx + 1}  ({len(lines)} linhas extraídas)")
        print(f"{'='*70}")

        for i, line in enumerate(lines):
            # Destaca linhas de apt, valores e possíveis separadores
            m_apt    = _RE_APT.match(line)
            valores  = _RE_VALOR.findall(line)
            tag = ""
            if m_apt:
                tag = f"  [APT={m_apt.group(1)} | vals={valores}]"
            elif valores:
                tag = f"  [vals={valores}]"

            print(f"  {i:03d}: {repr(line)}{tag}")

        print()

    doc.close()

if __name__ == "__main__":
    pdf = sys.argv[1] if len(sys.argv) > 1 else "input_pdfs/modelo3.pdf"
    run(pdf)
