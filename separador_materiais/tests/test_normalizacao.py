"""
Testes da lógica de normalização (parsing de quantidade e de-para).

Usa os dados reais de referência de um PSC de exemplo. Roda com pytest:

    pytest

ou diretamente (sem pytest instalado):

    python tests/test_normalizacao.py
"""

import os
import sys

import pandas as pd

# Permite importar os módulos da raiz do projeto ao rodar via pytest ou direto.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from normalizacao import normalizar_tabela, separar_quantidade  # noqa: E402


def test_separar_quantidade_casos_basicos():
    assert separar_quantidade("01 QSFP56 DR4+ MPO") == (1, "QSFP56 DR4+ MPO")
    assert separar_quantidade("04 WL5e") == (4, "WL5e")
    assert separar_quantidade("10 patch cords") == (10, "patch cords")


def test_separar_quantidade_mantem_nota_entre_parenteses():
    entrada = "08 cordões ópticos monofibra LC/PC- E2000/APC (Verificar com a regional)"
    qtd, item = separar_quantidade(entrada)
    assert qtd == 8
    assert item == "cordões ópticos monofibra LC/PC- E2000/APC (Verificar com a regional)"


def test_separar_quantidade_sem_numero():
    assert separar_quantidade("WL5e") == (None, "WL5e")
    assert separar_quantidade("") == (None, "")
    assert separar_quantidade(None) == (None, "")


def _tabela_referencia() -> pd.DataFrame:
    """Simula o DataFrame que o Docling devolveria para a tabela alvo."""
    return pd.DataFrame(
        [
            {
                "Destino": "EQUINIX SP4",
                "Equipamento": "01 QSFP56 DR4+ MPO",
                "Origem": "Engenharia",
                "Responsável": "ENGENHARIA",
                "Ação": "ADQUIRIR",
            },
            {
                "Destino": "FURNAS",
                "Equipamento": "01 WL5e",
                "Origem": "SP4 (PS 2055)",
                "Responsável": "ENGENHARIA",
                "Ação": "ADQUIRIR",
            },
            {
                "Destino": "BANDEIRANTES",
                "Equipamento": "08 cordões ópticos monofibra LC/PC- E2000/APC (Verificar com a regional)",
                "Origem": "Engenharia",
                "Responsável": "ENGENHARIA",
                "Ação": "ADQUIRIR",
            },
        ]
    )


def test_normalizar_tabela_completa():
    res = normalizar_tabela(_tabela_referencia())

    assert res.colunas_faltantes == []
    assert len(res.itens) == 3
    assert res.revisar.empty

    primeira = res.itens.iloc[0]
    assert primeira["destino"] == "EQUINIX SP4"
    assert primeira["quantidade"] == 1
    assert primeira["item"] == "QSFP56 DR4+ MPO"
    assert primeira["responsavel"] == "ENGENHARIA"
    assert primeira["acao"] == "ADQUIRIR"

    assert set(res.itens["destino"]) == {"EQUINIX SP4", "FURNAS", "BANDEIRANTES"}
    # ids estáveis e únicos
    assert res.itens["id_item"].is_unique


def test_linha_sem_quantidade_vai_para_revisar():
    df = _tabela_referencia()
    df.loc[len(df)] = {
        "Destino": "FURNAS",
        "Equipamento": "WL5e sem quantidade",
        "Origem": "Engenharia",
        "Responsável": "ENGENHARIA",
        "Ação": "ADQUIRIR",
    }
    res = normalizar_tabela(df)
    assert len(res.itens) == 3
    assert len(res.revisar) == 1
    assert res.revisar.iloc[0]["item"] == "WL5e sem quantidade"


def test_cabecalho_repetido_e_linha_vazia_sao_descartados():
    df = _tabela_referencia()
    # cabeçalho repetido (acontece em tabela multipágina)
    df.loc[len(df)] = {
        "Destino": "Destino",
        "Equipamento": "Equipamento",
        "Origem": "Origem",
        "Responsável": "Responsável",
        "Ação": "Ação",
    }
    # linha totalmente vazia
    df.loc[len(df)] = {k: "" for k in df.columns}
    res = normalizar_tabela(df)
    assert len(res.itens) == 3
    assert res.revisar.empty


if __name__ == "__main__":
    # Execução direta, sem depender do pytest.
    falhas = 0
    for nome, funcao in list(globals().items()):
        if nome.startswith("test_") and callable(funcao):
            try:
                funcao()
                print(f"OK   {nome}")
            except AssertionError as exc:
                falhas += 1
                print(f"FAIL {nome}: {exc}")
    print("\nTodos os testes passaram." if not falhas else f"\n{falhas} teste(s) falharam.")
    sys.exit(1 if falhas else 0)
