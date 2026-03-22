import re
from typing import List, Any

_RE_METER_READING = re.compile(
    r'M3:\s*[\d,.]+\s*\([^)]+\)\s*-\s*[\d,.]+\s*\([^)]+\)\s*=\s*[\d,.]+',
    re.IGNORECASE
)
_RE_VOLUME = re.compile(r'\d+[,.]\d+\s*m3', re.IGNORECASE)


def clean_description(text: str) -> str:
    """Remove ruídos de descrições de despesa (volumes, leituras de hidrômetro)
    preservando números de parcela (ex: '1/1', '3/18')."""
    if not text:
        return ""
    text = _RE_METER_READING.sub('', text)
    text = _RE_VOLUME.sub('', text)
    return clean_text(text)


def parse_valor_br(texto: str | None) -> float | None:
    """
    Converte string monetária brasileira para float de forma robusta.
    
    Suporta: '1.234,56', 'R$ 1.234,56', '1234,56', '1.234.567,89', '453,'
    """
    if not texto:
        return None
    
    # Remove símbolos de moeda e espaços extras
    limpo = re.sub(r'[R\$\s]', '', str(texto).strip())
    
    # Caso especial: '453,' -> '453,00'
    if limpo.endswith(','):
        limpo += '00'
    
    # Tenta casar formato BR com milhar (opcional) e decimal obrigatória
    # Ex: 1.234,56 ou 1234,56
    match = re.search(r'(-?)(\d{1,3}(?:\.\d{3})*|\d+),(\d{2})(?!\d)', limpo)
    if match:
        sinal = match.group(1)
        inteiro = match.group(2).replace(".", "")
        decimal = match.group(3)
        return float(f"{sinal}{inteiro}.{decimal}")
    
    return None

def clean_text(text: str) -> str:
    if not text: return ""
    return " ".join(text.split()).strip()

def group_words_by_line(words: List[Any], tolerance: int = 3) -> List[str]:
    """Agrupa palavras extraídas pelo PyMuPDF em linhas baseadas na coordenada Y."""
    if not words:
        return []

    words.sort(key=lambda w: (w[1], w[0]))
    
    lines = []
    current_line_words = [words[0]]
    current_y = words[0][1]
    
    for i in range(1, len(words)):
        word = words[i]
        if abs(word[1] - current_y) <= tolerance:
            current_line_words.append(word)
        else:
            current_line_words.sort(key=lambda w: w[0])
            lines.append(" ".join([w[4] for w in current_line_words]))
            current_line_words = [word]
            current_y = word[1]
            
    current_line_words.sort(key=lambda w: w[0])
    lines.append(" ".join([w[4] for w in current_line_words]))
    
    return lines
