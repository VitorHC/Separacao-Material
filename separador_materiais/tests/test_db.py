"""
Teste de integração da camada de banco (persistencia.py + db.py).

Exercita todo o ciclo real contra o PostgreSQL: criar schema, salvar, carregar,
listar (ativos/concluídos), editar itens/envios, concluir, reabrir e excluir.

Requer um PostgreSQL acessível (ex.: ``docker compose up -d``). Se não houver
banco, o teste é **pulado** (não falha) — assim o ``pytest`` continua verde
mesmo sem banco.

    pytest tests/test_db.py            # via pytest (pula se não houver banco)
    python tests/test_db.py            # direto (imprime OK / PULADO)
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import persistencia as ps  # noqa: E402

PSC = "ZZ TESTE-DB 99999"  # sentinela improvável de colidir com dados reais


def _banco_disponivel() -> bool:
    try:
        ps.inicializar()
        return True
    except Exception:  # noqa: BLE001 - sem banco: pula
        return False


def _rodar_ciclo() -> None:
    df = pd.DataFrame([
        {"destino": "EQUINIX SP4", "quantidade": 2, "item": "SPF-LX",
         "origem": "eng", "responsavel": "adm", "acao": "Remanejar"},
        {"destino": "FURNAS", "quantidade": 1, "item": "WL5e",
         "origem": "eng", "responsavel": "adm", "acao": "Adquirir"},
    ])
    ps.excluir(PSC)  # garante estado limpo

    # criar + salvar
    proj = ps.projeto_de_extracao(PSC, "verif.pdf", 3, "texto", df, "Autor X", "Resp Y")
    ps.salvar(proj)
    assert ps.existe(PSC)

    # carregar
    p = ps.carregar(PSC)
    assert p["autor"] == "Autor X" and p["responsavel_impl"] == "Resp Y"
    assert p["concluido"] is False
    assert len(p["itens"]) == 2 and p["itens"][0]["item"] == "SPF-LX"

    # editar item (marcar separado) + envio + salvar
    p["itens"][0]["separado"] = True
    p["envios"] = {"EQUINIX SP4": {"nf": "12345", "data_envio": "2026-06-23"}}
    ps.salvar(p)
    p2 = ps.carregar(PSC)
    assert p2["itens"][0]["separado"] is True
    assert p2["envios"]["EQUINIX SP4"]["nf"] == "12345"

    # atualizar pessoas sem reescrever itens
    ps.atualizar_pessoas(PSC, "Novo Autor", "Nova Resp")
    p3 = ps.carregar(PSC)
    assert p3["autor"] == "Novo Autor" and len(p3["itens"]) == 2

    # ativos vs concluídos
    ativos = {x["psc"] for x in ps.listar()}
    assert PSC in ativos
    ps.definir_conclusao(PSC, True)
    assert PSC not in {x["psc"] for x in ps.listar()}          # sumiu dos ativos
    assert PSC in {x["psc"] for x in ps.listar(concluido=True)}  # aparece em concluídos
    assert ps.carregar(PSC)["concluido"] is True

    # reabrir
    ps.definir_conclusao(PSC, False)
    assert PSC in {x["psc"] for x in ps.listar()}

    # excluir (cascata em itens/envios)
    ps.excluir(PSC)
    assert not ps.existe(PSC)


def test_ciclo_completo_db():
    if not _banco_disponivel():
        import pytest  # type: ignore

        pytest.skip("PostgreSQL indisponível — suba com 'docker compose up -d'.")
    _rodar_ciclo()


if __name__ == "__main__":
    if not _banco_disponivel():
        print("PULADO: PostgreSQL indisponível (rode 'docker compose up -d' antes).")
        sys.exit(0)
    try:
        _rodar_ciclo()
    finally:
        try:
            ps.excluir(PSC)
        except Exception:  # noqa: BLE001
            pass
    print("OK: ciclo completo do banco (salvar/carregar/listar/concluir/reabrir/excluir).")
