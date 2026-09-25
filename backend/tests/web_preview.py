"""Servidor descartável para testes E2E. Nunca usado pela aplicação real."""
from sqlalchemy import create_engine
from tempfile import TemporaryDirectory
from pathlib import Path
from backend.app.db import Base, session_factory
from backend.app.main import create_app
from backend.app.schemas import ProjetoEntrada
from backend.app.services import criar_projeto

_test_directory = TemporaryDirectory(prefix="separacao-e2e-")
engine = create_engine(f"sqlite:///{Path(_test_directory.name) / 'preview.db'}", connect_args={"check_same_thread": False})
Base.metadata.create_all(engine)
factory = session_factory(engine)
with factory.begin() as db:
    criar_projeto(db, ProjetoEntrada(codigo="PSC 2103", arquivo="PSC 2103 - Ampliação de capacidade.pdf", projetista="Equipe de engenharia", responsavel_implantacao="Implantação", itens=[
        {"destino":"EQUINIX SP4", "descricao":"Transceiver QSFP56 DR4+ MPO", "quantidade":4, "status":"separado", "serial":"400G • 500 m"},
        {"destino":"EQUINIX SP4", "descricao":"Cordão óptico LC/PC – E2000/APC", "quantidade":8, "status":"nao_separado"},
        {"destino":"FURNAS", "descricao":"Módulo óptico WL5e", "quantidade":2, "status":"outro_local", "local_origem":"Regional São Paulo"},
        {"destino":"BANDEIRANTES", "descricao":"Distribuidor óptico 24 posições", "quantidade":1, "status":"sem_estoque"},
    ]))
    criar_projeto(db, ProjetoEntrada(codigo="PS 2180", arquivo="PS 2180 - Interligação óptica.pdf", itens=[
        {"destino":"EQUINIX SP4", "descricao":"Transceiver SFP+ 10G LR", "quantidade":6, "status":"separado"},
        {"destino":"FURNAS", "descricao":"Cordão óptico LC/UPC – LC/UPC", "quantidade":12, "status":"separado"},
    ]))
app = create_app(engine)
