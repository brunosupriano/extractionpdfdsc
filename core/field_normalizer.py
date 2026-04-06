"""
Normalização canônica de categorias de despesas condominiais.

Mapeia qualquer variação de nome encontrada em PDFs para uma categoria
padronizada. Padrões compilados uma única vez no import.
"""
import re
from typing import Optional

# Mapeamento: categoria canônica → padrões regex (português + variações)
_CATEGORIAS: dict[str, list[str]] = {
    "AGUA": [
        r"\b[áa]gua\b",
        r"consumo\s+d[''´]?\s*[áa]gua",
        r"\bcorsan\b", r"\bsabesp\b", r"\bcedae\b",
        r"\bcopasa\b", r"\bcagece\b", r"\bcaern\b",
        r"\bembasa\b", r"\bcasan\b", r"\bsanepar\b",
        r"\bsanasa\b", r"\bsanep\b", r"\bdmae\b",
        r"tarifa\s+[áa]gua",
        r"abastecimento\s+[áa]gua",
        r"\bhidrom[eê]tro\b",
        r"leitura\s+hidr",
        r"taxa\s+[áa]gua",
        r"fornecimento\s+[áa]gua",
    ],
    "ESGOTO": [
        r"\besgoto\b",
        r"tratamento\s+esgoto",
        r"rede\s+esgoto",
        r"coleta\s+esgoto",
        r"[áa]gua\s+e\s+esgoto",
    ],
    "GAS": [
        r"\bg[áa]s\b",
        r"consumo\s+g[áa]s",
        r"fornecimento\s+g[áa]s",
        r"\bglp\b",
        r"g[áa]s\s+natural",
        r"g[áa]s\s+encanado",
        r"g[áa]s\s+condominial",
    ],
    "ENERGIA": [
        r"energia\s+el[eé]trica",
        r"energia\s+el[eé]t\.?",
        r"\bluz\b",
        r"\bceee\b", r"\bcopel\b", r"\bcemig\b",
        r"\beletropaulo\b", r"\bcpfl\b", r"\benel\b",
        r"\bcoelba\b", r"\benergi[sa]\b",
        r"\bampla\b", r"\blight\b", r"\bcocel\b",
        r"\bcoelce\b", r"\bceal\b",
        r"\bkwh\b",
        r"consumo\s+energ",
        r"energia\s+elet",
    ],
    "CONDOMINIO": [
        r"cond[oô]m[ií]nio(?!\s+de\s+festas)",
        r"taxa\s+condominial",
        r"cota\s+condominial",
        r"rateio\s+condominial",
        r"quota\s+condominial",
        r"fundo\s+de\s+custeio",
        r"despesa\s+ordin[aá]ria",
        r"cota\s+ordin[aá]ria",
        r"taxa\s+ordin[aá]ria",
    ],
    "SALAO_FESTAS": [
        r"sal[aã]o\s+de\s+festas",
        r"sal[aã]o\s+festas",
        r"uso\s+sal[aã]o",
        r"loca[cç][aã]o\s+sal[aã]o",
        r"reserva\s+sal[aã]o",
        r"sal[aã]o\s+eventos",
    ],
    "LAZER": [
        r"\blazer\b",
        r"\bpiscina\b",
        r"\bacademia\b",
        r"\bplayground\b",
        r"\bchurrasqueira\b",
        r"\bquiosque\b",
        r"uso\s+quiosque",
        r"\bquadra\b",
        r"\bspa\b",
        r"espa[cç]o\s+gourmet",
        r"sal[aã]o\s+de\s+jogos",
        r"sala\s+de\s+jogos",
        r"sal[aã]o\s+jogos",
        r"\bchurras\b",
        r"reserva\s+de\s+sal[aã]o",
    ],
    "LIMPEZA": [
        r"\blimpeza\b",
        r"\bconserva[cç][aã]o\b",
        r"\bzeladoria\b",
        r"\bhigieniza[cç][aã]o\b",
        r"\bdedetiza[cç][aã]o\b",
        r"\bdesinfe[cç][aã]o\b",
        r"limpeza\s+[áa]rea",
        r"\bfaxina\b",
        r"limpeza\s+predial",
        r"servi[cç]o\s+limpeza",
    ],
    "SEGURO": [
        r"\bseguros?\b",         # singular e plural
        r"seguro\s+condominial",
        r"seguro\s+predial",
        r"seguro\s+incendio",
        r"seguro\s+inc[eê]ndio",
        r"\bap[oó]lice\b",
        r"premio\s+seguro",
        r"prêmio\s+seguro",
    ],
    "FUNDO_RESERVA": [
        r"fundo\s+de?\s+reserva",
        r"fundo\s+reserva",
        r"reserva\s+de\s+capital",
        r"\bfr\b",
        r"fundo\s+obras",
    ],
    "MANUTENCAO": [
        r"manuten[cç][aã]o",
        r"\breparo\b",
        r"\breforma\b",
        r"\bobra\b",
        r"servi[cç]o\s+de\s+manuten",
        r"eletr[ií]c",
        r"hidr[aá]ulic",
        r"\bpintura\b",
        r"\bjardinagem\b",
        r"jardim\b",
        r"\binfra\b",
        r"recarga\s+extintor",
        r"\bextintores?\b",
        r"consertos?\s+e\s+reparos?",
        r"\bconsertos?\b",
        r"corte\s+de\s+grama",
        r"corte\s+grama",
    ],
    "ADMINISTRACAO": [
        r"administra[cç][aã]o",
        r"\badministradora\b",
        r"taxa\s+administrativa",
        r"\bgest[aã]o\b",
        r"\bhonor[aá]rios?\b",
        r"taxa\s+gest[aã]o",
        r"servi[cç]o\s+administr",
    ],
    "PORTARIA": [
        r"\bportaria\b",
        r"\bporteiro\b",
        r"seguran[cç]a\b",
        r"vigil[aâ]ncia",
        r"\bmonitoramento\b",
        r"\bcftv\b",
        r"controle\s+acesso",
        r"controle\s+de\s+acesso",
    ],
    "ISENCAO": [
        r"isen[cç][aã]o",
        r"\bdesconto\b",
        r"\bcr[eé]dito\b",
        r"\babatimento\b",
        r"devolu[cç][aã]o",
    ],
    "MULTA_JUROS": [
        r"\bmulta\b",
        r"\bjuros\b",
        r"\bmora\b",
        r"em\s+atraso",
        r"atualiza[cç][aã]o\s+monet[aá]ria",
        r"corre[cç][aã]o\s+monet[aá]ria",
        r"encargo\s+financeiro",
    ],
    "TAXA_EXTRA": [
        r"\bextra\b",
        r"taxa\s+extra",
        r"despesa\s+extra",
        r"rateio\s+extra",
        r"cobran[cç]a\s+extra",
        r"taxa\s+especial",
    ],
    "ESTACIONAMENTO": [
        r"\bgaragem\b",
        r"\bestacionamento\b",
        r"\bvaga\b",
        r"uso\s+garagem",
    ],
    "ELEVADOR": [
        r"\belevador\b",
        r"manuten[cç][aã]o\s+elevador",
        r"servi[cç]o\s+elevador",
    ],
    "TAXA_BANCARIA": [
        r"taxa\s+banc[aá]ria",
        r"tarifa\s+banc[aá]ria",
        r"\bbanco\b",
        r"boleto\b",
        r"emiss[aã]o\s+boleto",
        r"despesas?\s+banc[aá]rias?",
        r"transfer[eê]ncia\s+entre\s+bancos",
        r"taxa\s+expedi[eê]nte",
        r"certificado\s+digital",
    ],
    "SINDICO": [
        r"pr[oó]\s*labore",
        r"pro\s*labore",
        r"honor[aá]rios?\s+s[ií]ndico",
        r"\bs[ií]ndico\b",
        r"subsind[ií]co",
    ],
}

# Compilar tudo de uma vez no import (custo único)
_COMPILED: list[tuple[str, re.Pattern]] = [
    (cat, re.compile("|".join(patterns), re.IGNORECASE))
    for cat, patterns in _CATEGORIAS.items()
]


def normalize_tipo_despesa(descricao: str) -> Optional[str]:
    """Retorna categoria canônica ou None se não reconhecida.

    Percorre os padrões em ordem de prioridade. A ordem importa:
    ESGOTO deve vir antes de AGUA porque "água e esgoto" encaixaria em AGUA.
    """
    if not descricao:
        return None
    for categoria, pattern in _COMPILED:
        if pattern.search(descricao):
            return categoria
    return None
