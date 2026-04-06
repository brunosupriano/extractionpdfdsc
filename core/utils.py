import re
from typing import List, Any, Optional

# Leitura completa de hidrômetro: "M3: 100,5 (01/01) - 90,0 (01/12) = 10,5"
_RE_METER_READING = re.compile(
    r'M3:\s*[\d,.]+\s*\([^)]+\)\s*-\s*[\d,.]+\s*\([^)]+\)\s*=\s*[\d,.]+',
    re.IGNORECASE
)
# Captura o consumo (último número) da leitura de hidrômetro
_RE_METER_READING_CAPTURE = re.compile(
    r'M3:\s*[\d,.]+\s*\([^)]+\)\s*-\s*[\d,.]+\s*\([^)]+\)\s*=\s*([\d,.]+)',
    re.IGNORECASE
)
# Volume inline: "3,506 m3" ou "3.506 m3"
_RE_VOLUME = re.compile(r'[\d,.]+\s*m3', re.IGNORECASE)
_RE_VOLUME_CAPTURE = re.compile(r'([\d,.]+)\s*m3', re.IGNORECASE)


def _parse_volume_flexivel(texto: str) -> Optional[float]:
    """Converte string numérica de volume para float.

    Mais flexível que parse_valor_br: aceita 1-4 casas decimais,
    necessário para volumes em m³ (ex: '10,5', '3,506', '1,2345').
    Separador decimal = vírgula (padrão BR); milhar = ponto (opcional).
    """
    if not texto:
        return None
    limpo = re.sub(r'[R\$\s]', '', str(texto).strip())
    # Formato BR: dígitos(opcionalmente separados por ponto) + vírgula + 1-4 dígitos
    m = re.search(r'(-?)(\d{1,3}(?:\.\d{3})*|\d+),(\d{1,4})(?!\d)', limpo)
    if m:
        sinal = m.group(1)
        inteiro = m.group(2).replace('.', '')
        decimal = m.group(3)
        try:
            return float(f"{sinal}{inteiro}.{decimal}")
        except ValueError:
            return None
    return None


def extract_volume_m3(text: str) -> Optional[float]:
    """Extrai o volume consumido em m³ de uma linha de despesa.

    Reconhece dois formatos:
    1. Leitura de hidrômetro: "M3: 100,5 (01/01) - 90,0 (01/12) = 10,5"
       → retorna o consumo (parte após o '=')
    2. Volume inline: "3,506 m3" ou "10,5m3"
       → retorna o valor diretamente

    Usa parser flexível pois volumes podem ter 1–4 casas decimais.
    """
    if not text:
        return None
    m = _RE_METER_READING_CAPTURE.search(text)
    if m:
        return _parse_volume_flexivel(m.group(1))
    m = _RE_VOLUME_CAPTURE.search(text)
    if m:
        return _parse_volume_flexivel(m.group(1))
    return None


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
