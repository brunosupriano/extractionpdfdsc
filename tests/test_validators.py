import pytest
from models import DadosApartamento, ItemDespesa, ValidationStatus

def test_validacao_financeira_sucesso():
    """Testa se a validação retorna OK quando a soma bate com o total impresso."""
    apt = DadosApartamento(apartamento="101", total_impresso=100.0)
    apt.despesas.append(ItemDespesa(descricao="Luz", valor=60.0))
    apt.despesas.append(ItemDespesa(descricao="Água", valor=40.0))
    
    apt.calcular_validacao(tolerancia=0.5)
    
    assert apt.status_validacao == ValidationStatus.OK
    assert apt.soma_calculada == 100.0
    assert apt.taxa_assertividade == 100.0

def test_validacao_financeira_divergente():
    """Testa se a validação retorna DIVERGENTE quando a soma não bate."""
    apt = DadosApartamento(apartamento="202", total_impresso=100.0)
    apt.despesas.append(ItemDespesa(descricao="Luz", valor=60.0))
    apt.despesas.append(ItemDespesa(descricao="Água", valor=30.0)) # Soma = 90
    
    apt.calcular_validacao(tolerancia=0.5)
    
    assert apt.status_validacao == ValidationStatus.DIVERGENTE
    assert apt.taxa_assertividade == 90.0

def test_validacao_sem_total_impresso():
    """Testa o comportamento quando o PDF não informa o total do apartamento."""
    apt = DadosApartamento(apartamento="303", total_impresso=None)
    apt.despesas.append(ItemDespesa(descricao="Luz", valor=50.0))
    
    apt.calcular_validacao()
    
    assert apt.status_validacao == ValidationStatus.SEM_TOTAL
