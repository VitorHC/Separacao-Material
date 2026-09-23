import json

import pytest
from sqlalchemy import func, select

from backend.app.migrate_json import MigrationError, migrar_pasta
from backend.app.models import ImportacaoLegada, Item, Projeto, Remessa


def write(folder, codigo="PS 100", nome="projeto.json", **extra):
    value = {"psc": codigo, "arquivo": "projeto.pdf", "paginas": 2,
             "itens": [{"destino": "SITE A", "quantidade": 3, "item": "Modulo", "separado": True}], **extra}
    p = folder / nome
    p.write_text(json.dumps(value), encoding="utf-8")
    return p


def count(factory, model):
    with factory() as db:
        return db.scalar(select(func.count()).select_from(model))


def test_simulacao_e_reexecucao_sem_duplicidade(factory, tmp_path):
    write(tmp_path)
    report = migrar_pasta(factory, tmp_path)
    assert report["arquivos"][0]["resultado"] == "simulado"
    assert count(factory, Projeto) == 0
    migrar_pasta(factory, tmp_path, apply=True)
    assert count(factory, Projeto) == 1
    report = migrar_pasta(factory, tmp_path, apply=True)
    assert report["arquivos"][0]["resultado"] == "ja_importado"
    assert count(factory, Item) == 1


def test_preserva_incompletos_e_original(factory, tmp_path):
    path = write(tmp_path, itens=[{"item":"Modulo", "quantidade":None},
        {"destino":"SITE A", "quantidade":1.7, "item":"Cabo", "separado":True, "sem_estoque":True}])
    migrar_pasta(factory, tmp_path, apply=True)
    with factory() as db:
        rows = list(db.scalars(select(Item)))
        assert len(rows) == 2 and all(r.revisao for r in rows)
        assert all(r.quantidade is None for r in rows)
        assert rows[1].status == "sem_estoque"
        assert db.scalar(select(ImportacaoLegada)).original == json.loads(path.read_text())


def test_pasta_invalida_nao_parece_sucesso(factory, tmp_path):
    with pytest.raises(MigrationError):
        migrar_pasta(factory, tmp_path, apply=True)


def test_erro_no_segundo_arquivo_reverte_lote(factory, tmp_path):
    write(tmp_path, nome="a.json")
    (tmp_path / "b.json").write_text("{quebrado")
    with pytest.raises(MigrationError):
        migrar_pasta(factory, tmp_path, apply=True)
    assert count(factory, Projeto) == 0
    assert count(factory, Item) == 0


def test_conflito_nao_sobrescreve_dados(factory, tmp_path):
    path = write(tmp_path)
    migrar_pasta(factory, tmp_path, apply=True)
    write(tmp_path, arquivo="novo.pdf")
    with pytest.raises(MigrationError):
        migrar_pasta(factory, tmp_path, apply=True)
    with factory() as db:
        assert db.scalar(select(Projeto)).arquivo == "projeto.pdf"


def test_nf_legada_nao_inventa_quantidades_enviadas(factory, client, tmp_path):
    write(tmp_path, envios={"SITE A": {"nf":"000123", "data_envio":"2026-01-15"}})
    migrar_pasta(factory, tmp_path, apply=True)
    r = client.get("/remessas").json()[0]
    assert r["nf"] == "000123" and r["status"] == "legado_revisar"
    assert r["itens"] == []
    i = client.get("/consolidado").json()[0]["itens"][0]
    assert i["quantidade_entregue_logistica"] == 0 and i["revisao"]
    assert client.post("/remessas", json={"localidade_id":i["localidade_id"],
        "itens":[{"item_id":i["id"],"quantidade":1}]}).status_code == 409
    result = client.post(f"/remessas/{r['id']}/reconciliar-legado", json={"nf":"000123",
        "data_entrega_logistica":"2026-01-15", "itens":[{"item_id":i["id"], "quantidade":2}]})
    assert result.status_code == 200, result.text
    i = client.get("/consolidado").json()[0]["itens"][0]
    assert i["quantidade_entregue_logistica"] == 2 and i["quantidade_pendente"] == 1
    assert client.post(f"/itens/{i['id']}/conferir").status_code == 200
    assert client.post("/remessas", json={"localidade_id":i["localidade_id"],
        "itens":[{"item_id":i["id"],"quantidade":1}]}).status_code == 201


def test_nao_mescla_nfs_iguais_sem_confirmacao(factory, tmp_path):
    for n in range(2):
        write(tmp_path, f"PS {100+n}", f"{n}.json", envios={"SITE A":{"nf":"123"}})
    migrar_pasta(factory, tmp_path, apply=True)
    assert count(factory, Remessa) == 2
