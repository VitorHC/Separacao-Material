"""
persistencia.py
===============

Armazenamento dos projetos em **PostgreSQL** — fonte única de verdade do app.
A infraestrutura de conexão/schema fica em :mod:`db`.

Modelo (ver ``db.SCHEMA``):
    * **projetos** — 1 linha por PSC (arquivo, método, as duas pessoas, conclusão).
    * **itens**    — itens do projeto (separado, sem_estoque, destino, etc.), em ordem.
    * **envios**   — NF e data de envio por destino (local).

A camada expõe o projeto como um ``dict`` (mesmo formato usado pela UI)::

    {
      "psc": "PS 2103", "arquivo": "...", "paginas": 6, "metodo": "texto",
      "autor": "Fulano", "responsavel_impl": "Ciclana",
      "concluido": False, "concluido_em": "", "criado_em": "...", "atualizado_em": "...",
      "itens": [ {"separado": False, "sem_estoque": False, "destino": "EQUINIX SP4",
                  "quantidade": 2, "item": "SPF-LX", "tipo": "", "serial": "",
                  "origem": "engenharia", "responsavel": "administração",
                  "acao": "Remanejar"}, ... ],
      "envios": { "EQUINIX SP4": {"nf": "12345", "data_envio": "2026-06-23"} }
    }
"""

from __future__ import annotations

import re
from typing import Optional

import pandas as pd

from db import conexao, inicializar  # noqa: F401  (inicializar reexportado p/ o app)

#: Colunas dos itens, na ordem usada na tabela editável.
COLUNAS_ITEM = [
    "separado",
    "sem_estoque",
    "destino",
    "quantidade",
    "item",
    "tipo",
    "serial",
    "origem",
    "responsavel",
    "acao",
]

#: Colunas booleanas (checkbox).
_COLS_BOOL = ("separado", "sem_estoque")
#: Colunas de texto do item.
_COLS_TEXTO = ("destino", "item", "tipo", "serial", "origem", "responsavel", "acao")


# ---------------------------------------------------------------------------
# Helpers de valor
# ---------------------------------------------------------------------------

def _slug(texto: str) -> str:
    """Slug seguro para nomes de arquivo de exportação (Excel/CSV/PDF)."""
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(texto)).strip("_") or "sem_psc"


def _quantidade_int(valor: object) -> Optional[int]:
    """Converte quantidade para int, tolerando NA/''/floats."""
    try:
        vazio = valor is None or pd.isna(valor)
    except (TypeError, ValueError):
        vazio = valor is None
    if vazio or str(valor).strip() in ("", "nan", "<NA>", "None"):
        return None
    try:
        return int(float(valor))
    except (ValueError, TypeError):
        return None


def _txt(valor: object) -> str:
    return str(valor if valor is not None else "").strip()


def _iso(valor: object) -> str:
    """datetime/date -> string ISO (segundos); '' para nulos."""
    if valor is None:
        return ""
    try:
        return valor.isoformat(timespec="seconds")  # datetime
    except TypeError:
        return valor.isoformat()                     # date
    except AttributeError:
        return str(valor)


def normalizar_item(d: dict) -> dict:
    """Padroniza um dicionário de item (tipos e chaves)."""
    return {
        "separado": bool(d.get("separado", False)),
        "sem_estoque": bool(d.get("sem_estoque", False)),
        "destino": _txt(d.get("destino")),
        "quantidade": _quantidade_int(d.get("quantidade")),
        "item": _txt(d.get("item")),
        "tipo": _txt(d.get("tipo")),
        "serial": _txt(d.get("serial")),
        "origem": _txt(d.get("origem")),
        "responsavel": _txt(d.get("responsavel")),
        "acao": _txt(d.get("acao")),
    }


# ---------------------------------------------------------------------------
# Linha do banco -> dict
# ---------------------------------------------------------------------------

def _item_de_linha(r: dict) -> dict:
    return {
        "separado": bool(r["separado"]),
        "sem_estoque": bool(r["sem_estoque"]),
        "destino": r["destino"] or "",
        "quantidade": r["quantidade"],
        "item": r["item"] or "",
        "tipo": r["tipo"] or "",
        "serial": r["serial"] or "",
        "origem": r["origem"] or "",
        "responsavel": r["responsavel"] or "",
        "acao": r["acao"] or "",
    }


def _projeto_de_linha(r: dict, itens: list[dict], envios: dict) -> dict:
    return {
        "psc": r["psc"],
        "arquivo": r["arquivo"] or "",
        "paginas": r["paginas"],
        "metodo": r["metodo"] or "",
        "autor": r["autor"] or "",
        "responsavel_impl": r["responsavel_impl"] or "",
        "concluido": bool(r["concluido"]),
        "concluido_em": _iso(r["concluido_em"]),
        "criado_em": _iso(r["criado_em"]),
        "atualizado_em": _iso(r["atualizado_em"]),
        "itens": itens,
        "envios": envios,
    }


def _cursor(conn):
    from psycopg2.extras import RealDictCursor

    return conn.cursor(cursor_factory=RealDictCursor)


# ---------------------------------------------------------------------------
# CRUD de projetos
# ---------------------------------------------------------------------------

def existe(psc: str) -> bool:
    with conexao() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM projetos WHERE psc = %s", (psc,))
        return cur.fetchone() is not None


def salvar(projeto: dict) -> None:
    """Grava projeto + itens + envios (substitui itens/envios do PSC).

    A conclusão (``concluido``/``concluido_em``) é gerida por
    :func:`definir_conclusao` e **não** é alterada aqui.
    """
    from psycopg2.extras import execute_values

    psc = projeto["psc"]
    itens = [normalizar_item(i) for i in projeto.get("itens", [])]
    envios = projeto.get("envios", {})

    with conexao() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO projetos (psc, arquivo, paginas, metodo, autor, responsavel_impl)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (psc) DO UPDATE SET
                arquivo = EXCLUDED.arquivo, paginas = EXCLUDED.paginas,
                metodo = EXCLUDED.metodo, autor = EXCLUDED.autor,
                responsavel_impl = EXCLUDED.responsavel_impl, atualizado_em = now()
            """,
            (psc, projeto.get("arquivo", ""), projeto.get("paginas"),
             projeto.get("metodo", ""), projeto.get("autor", ""),
             projeto.get("responsavel_impl", "")),
        )
        cur.execute("DELETE FROM itens WHERE psc = %s", (psc,))
        if itens:
            execute_values(
                cur,
                "INSERT INTO itens (psc, ordem, separado, sem_estoque, destino,"
                " quantidade, item, tipo, serial, origem, responsavel, acao) VALUES %s",
                [(psc, k, i["separado"], i["sem_estoque"], i["destino"], i["quantidade"],
                  i["item"], i["tipo"], i["serial"], i["origem"], i["responsavel"], i["acao"])
                 for k, i in enumerate(itens)],
            )
        cur.execute("DELETE FROM envios WHERE psc = %s", (psc,))
        linhas_env = [(psc, d, v.get("nf", ""), v.get("data_envio", ""))
                      for d, v in envios.items() if d]
        if linhas_env:
            execute_values(
                cur, "INSERT INTO envios (psc, destino, nf, data_envio) VALUES %s", linhas_env
            )


def carregar(psc: str) -> Optional[dict]:
    with conexao() as conn, _cursor(conn) as cur:
        cur.execute("SELECT * FROM projetos WHERE psc = %s", (psc,))
        proj = cur.fetchone()
        if proj is None:
            return None
        cur.execute("SELECT * FROM itens WHERE psc = %s ORDER BY ordem", (psc,))
        itens = [_item_de_linha(r) for r in cur.fetchall()]
        cur.execute("SELECT destino, nf, data_envio FROM envios WHERE psc = %s", (psc,))
        envios = {r["destino"]: {"nf": r["nf"] or "", "data_envio": r["data_envio"] or ""}
                  for r in cur.fetchall()}
    return _projeto_de_linha(proj, itens, envios)


def excluir(psc: str) -> None:
    with conexao() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM projetos WHERE psc = %s", (psc,))  # cascata em itens/envios


def definir_conclusao(psc: str, concluido: bool) -> None:
    """Marca/desmarca o projeto como concluído (define/limpa ``concluido_em``)."""
    with conexao() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE projetos SET concluido = %s,"
            " concluido_em = CASE WHEN %s THEN now() ELSE NULL END,"
            " atualizado_em = now() WHERE psc = %s",
            (concluido, concluido, psc),
        )


def atualizar_pessoas(psc: str, autor: str, responsavel_impl: str) -> None:
    """Atualiza só as duas pessoas do projeto (sem reescrever itens)."""
    with conexao() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE projetos SET autor = %s, responsavel_impl = %s,"
            " atualizado_em = now() WHERE psc = %s",
            (autor.strip(), responsavel_impl.strip(), psc),
        )


def listar(concluido: Optional[bool] = False) -> list[dict]:
    """Projetos completos (com itens e envios), ordenados por PSC.

    ``concluido=False`` (padrão) traz só os ativos; ``True`` só os concluídos;
    ``None`` traz todos.
    """
    where, params = "", ()
    if concluido is not None:
        where, params = "WHERE concluido = %s", (concluido,)

    with conexao() as conn, _cursor(conn) as cur:
        cur.execute(f"SELECT * FROM projetos {where} ORDER BY psc", params)
        projs = cur.fetchall()
        if not projs:
            return []
        pscs = [p["psc"] for p in projs]
        cur.execute("SELECT * FROM itens WHERE psc = ANY(%s) ORDER BY psc, ordem", (pscs,))
        itens_rows = cur.fetchall()
        cur.execute("SELECT destino, nf, data_envio, psc FROM envios WHERE psc = ANY(%s)", (pscs,))
        envios_rows = cur.fetchall()

    itens_por_psc: dict[str, list[dict]] = {}
    for r in itens_rows:
        itens_por_psc.setdefault(r["psc"], []).append(_item_de_linha(r))
    envios_por_psc: dict[str, dict] = {}
    for r in envios_rows:
        envios_por_psc.setdefault(r["psc"], {})[r["destino"]] = {
            "nf": r["nf"] or "", "data_envio": r["data_envio"] or ""
        }

    return [_projeto_de_linha(p, itens_por_psc.get(p["psc"], []), envios_por_psc.get(p["psc"], {}))
            for p in projs]


# ---------------------------------------------------------------------------
# Conversões item <-> DataFrame  (usadas pela tabela editável da UI)
# ---------------------------------------------------------------------------

def itens_df(projeto: dict) -> pd.DataFrame:
    """DataFrame dos itens (para a tabela editável)."""
    itens = projeto.get("itens", [])
    df = pd.DataFrame(itens) if itens else pd.DataFrame(columns=COLUNAS_ITEM)
    for c in COLUNAS_ITEM:
        if c not in df.columns:
            df[c] = False if c in _COLS_BOOL else (pd.NA if c == "quantidade" else "")
    df = df[COLUNAS_ITEM].copy()
    for c in _COLS_BOOL:
        df[c] = df[c].fillna(False).astype(bool)
    df["quantidade"] = pd.to_numeric(df["quantidade"], errors="coerce").astype("Int64")
    for c in _COLS_TEXTO:
        df[c] = df[c].fillna("").astype(str)
    return df


def df_para_itens(df: pd.DataFrame) -> list[dict]:
    """Converte a tabela editada de volta para a lista de itens (limpa vazios)."""
    itens = []
    for _, linha in df.iterrows():
        item = normalizar_item(linha.to_dict())
        if not item["destino"] and not item["item"]:
            continue  # linha em branco
        itens.append(item)
    return itens


def projeto_de_extracao(
    psc: str, arquivo: str, paginas: int, metodo: str, itens_norm: pd.DataFrame,
    autor: str = "", responsavel_impl: str = "",
) -> dict:
    """Monta um projeto novo a partir do DataFrame normalizado da extração."""
    itens = [
        normalizar_item({
            "destino": r.get("destino", ""),
            "quantidade": r.get("quantidade"),
            "item": r.get("item", ""),
            "origem": r.get("origem", ""),
            "responsavel": r.get("responsavel", ""),
            "acao": r.get("acao", ""),
        })
        for _, r in itens_norm.iterrows()
    ]
    return {
        "psc": psc,
        "arquivo": arquivo,
        "paginas": paginas,
        "metodo": metodo,
        "autor": autor.strip(),
        "responsavel_impl": responsavel_impl.strip(),
        "concluido": False,
        "concluido_em": "",
        "itens": itens,
        "envios": {},
    }
