"""
db.py
=====

Conexão e schema do **PostgreSQL** — infraestrutura usada por ``persistencia.py``.

Configuração (variáveis de ambiente, com defaults para o docker-compose):

    DATABASE_URL   postgresql://usuario:senha@host:porta/banco   (tem prioridade)
    — ou, individualmente —
    PGHOST=localhost  PGPORT=5432  PGUSER=postgres
    PGPASSWORD=postgres  PGDATABASE=separador_materiais

``inicializar()`` cria o banco (se faltar) e as tabelas — é idempotente e roda
uma única vez por processo. O import do ``psycopg2`` é preguiçoso para não pesar
na importação do módulo nem quebrar em ambientes sem o driver instalado.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from urllib.parse import urlparse

#: DDL do schema (idempotente). Um projeto = 1 PSC; itens e envios em cascata.
SCHEMA = """
CREATE TABLE IF NOT EXISTS projetos (
    psc               TEXT PRIMARY KEY,
    arquivo           TEXT,
    paginas           INTEGER,
    metodo            TEXT,
    autor             TEXT,               -- quem fez o projeto
    responsavel_impl  TEXT,               -- quem dá seguimento na implantação
    concluido         BOOLEAN NOT NULL DEFAULT FALSE,
    concluido_em      TIMESTAMP,
    criado_em         TIMESTAMP NOT NULL DEFAULT now(),
    atualizado_em     TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS itens (
    id           BIGSERIAL PRIMARY KEY,
    psc          TEXT NOT NULL REFERENCES projetos(psc) ON DELETE CASCADE,
    ordem        INTEGER NOT NULL,
    separado     BOOLEAN NOT NULL DEFAULT FALSE,
    sem_estoque  BOOLEAN NOT NULL DEFAULT FALSE,
    destino      TEXT,
    quantidade   INTEGER,
    item         TEXT,
    tipo         TEXT,
    serial       TEXT,
    origem       TEXT,
    responsavel  TEXT,
    acao         TEXT
);
CREATE INDEX IF NOT EXISTS itens_psc_idx ON itens (psc);

CREATE TABLE IF NOT EXISTS envios (
    psc         TEXT NOT NULL REFERENCES projetos(psc) ON DELETE CASCADE,
    destino     TEXT NOT NULL,
    nf          TEXT,
    data_envio  TEXT,
    PRIMARY KEY (psc, destino)
);
"""

_inicializado = False


# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

def _config() -> dict:
    """Parâmetros de conexão (kwargs do psycopg2), a partir do ambiente."""
    url = os.environ.get("DATABASE_URL")
    if url:
        u = urlparse(url)
        return {
            "host": u.hostname or "localhost",
            "port": u.port or 5432,
            "user": u.username or "postgres",
            "password": u.password or "",
            "dbname": (u.path or "").lstrip("/") or "separador_materiais",
        }
    return {
        "host": os.environ.get("PGHOST", "localhost"),
        "port": int(os.environ.get("PGPORT", "5432")),
        "user": os.environ.get("PGUSER", "postgres"),
        "password": os.environ.get("PGPASSWORD", "postgres"),
        "dbname": os.environ.get("PGDATABASE", "separador_materiais"),
    }


# ---------------------------------------------------------------------------
# Conexão
# ---------------------------------------------------------------------------

@contextmanager
def conexao():
    """Abre uma conexão, faz commit ao sair (ou rollback em erro) e fecha.

    Uso::

        with conexao() as conn, conn.cursor() as cur:
            cur.execute(...)
    """
    import psycopg2  # import preguiçoso (driver só é exigido em runtime)

    conn = psycopg2.connect(**_config())
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Inicialização (cria banco + tabelas)
# ---------------------------------------------------------------------------

def _criar_banco_se_faltar(cfg: dict) -> None:
    """Conecta no banco de manutenção ``postgres`` e cria o banco-alvo se ele
    ainda não existir. Silencioso se não houver permissão (assume que já existe)."""
    import psycopg2
    from psycopg2 import sql

    admin = {**cfg, "dbname": "postgres"}
    try:
        conn = psycopg2.connect(**admin)
    except Exception:
        return  # sem acesso ao 'postgres'; segue e tenta criar as tabelas direto
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (cfg["dbname"],))
            if cur.fetchone() is None:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(cfg["dbname"])))
    finally:
        conn.close()


def inicializar(forcar: bool = False) -> None:
    """Garante banco e tabelas. Idempotente; roda uma vez por processo."""
    global _inicializado
    if _inicializado and not forcar:
        return
    cfg = _config()
    _criar_banco_se_faltar(cfg)
    with conexao() as conn, conn.cursor() as cur:
        cur.execute(SCHEMA)
    _inicializado = True
