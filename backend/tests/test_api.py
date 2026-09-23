from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pytest
from fastapi import HTTPException

from backend.app.models import Item
from backend.app.schemas import ProjetoEntrada, RemessaEntrada
from backend.app.services import criar_projeto, criar_remessa


def project(c, codigo="PS 100", destino="SITE A", status="separado", qtd=10, **extras):
    r = c.post("/projetos", json={"codigo": codigo, "itens": [{"destino": destino,
        "descricao": "Módulo óptico", "quantidade": qtd, "status": status, **extras}]})
    assert r.status_code == 201, r.text
    return r.json()


def shipment(c, *projects, qtd=2, **extra):
    return c.post("/remessas", json={"localidade_id": projects[0]["itens"][0]["localidade_id"],
        "itens": [{"item_id": p["itens"][0]["id"], "quantidade": qtd} for p in projects], **extra})


def test_consolida_projetos_em_uma_nf_e_envio_parcial(client):
    p1 = project(client)
    p2 = project(client, "PSC 200", " site   a ")
    assert len(client.get("/localidades").json()) == 1
    cons = client.get("/consolidado").json()
    assert len(cons) == 1 and len(cons[0]["itens"]) == 2
    r = shipment(client, p1, p2)
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert {i["codigo_projeto"] for i in r.json()["itens"]} == {"PS 100", "PSC 200"}
    assert client.post(f"/remessas/{rid}/solicitar-nf").json()["status"] == "nf_solicitada"
    assert client.put(f"/remessas/{rid}/nf", json={"nf": "000123"}).status_code == 200
    result = client.post(f"/remessas/{rid}/entregar-logistica", json={"data_entrega_logistica": str(date.today())})
    assert result.status_code == 200
    assert result.json()["nf"] == "000123"
    for i in client.get("/consolidado").json()[0]["itens"]:
        assert i["quantidade_entregue_logistica"] == 2
        assert i["quantidade_pendente"] == 8
        assert i["quantidade_reservada"] == 0
    assert client.post(f"/remessas/{rid}/cancelar").status_code == 409


def test_codigo_normalizado_e_prefixos_distintos(client):
    project(client, "ps-00100")
    r = client.post("/projetos", json={"codigo": "PS 100"})
    assert r.status_code == 409
    assert client.post("/projetos", json={"codigo": "PSC 100"}).status_code == 201
    assert client.post("/projetos", json={"codigo": "sem numero"}).status_code == 422


@pytest.mark.parametrize("status,cor", [("nao_separado","branco"),("separado","verde"),("outro_local","amarelo"),("sem_estoque","vermelho")])
def test_cores_e_elegibilidade(client, status, cor):
    p = project(client, status=status)
    assert p["itens"][0]["cor"] == cor
    assert shipment(client, p).status_code == (201 if status == "separado" else 409)


def test_amarelo_exige_origem_compativel(client):
    p = project(client, status="outro_local", local_origem="SITE B")
    assert shipment(client, p, origem_expedicao="SITE C").status_code == 409
    assert shipment(client, p, origem_expedicao="site b").status_code == 201


def test_nao_mistura_destinos_nem_origens(client):
    p = project(client)
    q = project(client, "PS 101", "SITE B")
    assert shipment(client, p, q).status_code == 422
    q = project(client, "PS 102", status="outro_local", local_origem="FILIAL")
    assert shipment(client, p, q).status_code == 409


def test_reserva_saldo_e_cancelamento(client):
    p = project(client, qtd=3)
    r = shipment(client, p, qtd=2).json()
    assert shipment(client, p, qtd=2).status_code == 409
    i = client.get("/consolidado").json()[0]["itens"][0]
    assert i["quantidade_reservada"] == 2 and i["quantidade_disponivel_remessa"] == 1
    assert client.post(f"/remessas/{r['id']}/cancelar").status_code == 200
    assert shipment(client, p, qtd=3).status_code == 201


def test_envio_exige_nf_e_data_nao_futura(client):
    p = project(client)
    rid = shipment(client, p).json()["id"]
    assert client.post(f"/remessas/{rid}/entregar-logistica", json={"data_entrega_logistica": str(date.today())}).status_code == 409
    assert client.put(f"/remessas/{rid}/nf", json={"nf": "  "}).status_code == 422
    client.put(f"/remessas/{rid}/nf", json={"nf": "123"})
    assert client.post(f"/remessas/{rid}/entregar-logistica", json={"data_entrega_logistica": str(date.today()+timedelta(days=1))}).status_code == 422


def test_edicao_nao_altera_material_reservado(client):
    p = project(client)
    r = shipment(client, p).json()
    item_id = p["itens"][0]["id"]
    data = {"destino": "SITE B", "descricao": "Novo", "quantidade": 5}
    assert client.put(f"/itens/{item_id}", json=data).status_code == 409
    client.post(f"/remessas/{r['id']}/cancelar")
    assert client.put(f"/itens/{item_id}", json=data).status_code == 200


def test_filtros_consolidado(client):
    p = project(client)
    project(client, "PS 101", "SITE B", status="sem_estoque")
    r = client.get("/consolidado", params={"projeto_id": p["id"]}).json()
    assert len(r) == 1 and r[0]["itens"][0]["codigo_projeto"] == "PS 100"
    r = client.get("/consolidado", params={"status": "sem_estoque"}).json()
    assert len(r) == 1 and r[0]["destino"] == "SITE B"


def test_rejeita_duplicata_de_item_na_remessa(client):
    p = project(client)
    assert shipment(client, p, p).status_code == 422
    assert client.get("/remessas").json() == []


@pytest.mark.parametrize("qtd", [0, -1, 1.5, True])
def test_quantidade_invalida(client, qtd):
    r = client.post("/projetos", json={"codigo": "PS 100", "itens": [
        {"destino": "SITE A", "descricao": "Modulo", "quantidade": qtd}]})
    assert r.status_code == 422
    assert client.get("/projetos").json() == []


def test_concorrencia_nao_reserva_duas_vezes(engine, factory):
    if engine.dialect.name != "postgresql":
        pytest.skip("Lock de saldo exige PostgreSQL real; executado no CI.")
    with factory.begin() as db:
        p = criar_projeto(db, ProjetoEntrada(codigo="PS 100", itens=[{
            "destino": "SITE A", "descricao": "Modulo", "quantidade": 3, "status": "separado"}]))
        i = db.query(Item).one()
        data = RemessaEntrada(localidade_id=i.localidade_id, itens=[{"item_id": i.id, "quantidade": 2}])
    def reserve():
        try:
            with factory.begin() as db:
                criar_remessa(db, data)
            return "ok"
        except HTTPException as exc:
            return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: reserve(), range(2)))
    assert sorted(map(str, results)) == ["409", "ok"]
