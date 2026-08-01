# validators.py
from stdnum.es import dni, nif, cif
from stdnum import iban as std_iban

def validar_nif_cif(valor: str) -> bool:
    if not valor:
        return True
    valor = valor.strip().upper().replace('-', '').replace(' ', '')
    return dni.is_valid(valor) or nif.is_valid(valor) or cif.is_valid(valor)

def validar_iban(valor: str) -> bool:
    if not valor:
        return True
    valor = valor.strip().replace(' ', '')
    return std_iban.is_valid(valor)
