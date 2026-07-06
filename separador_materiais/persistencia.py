"""
persistencia.py
===============

Armazenamento em disco dos projetos — fonte única de verdade do app.

Cada projeto (1 PSC) é um arquivo JSON em ``dados/projetos/<slug>.json``:

    {
      "psc": "PS 2103",
      "arquivo": "PS 2103 - ....pdf",
      "paginas": 6,
      "metodo": "texto",
      "criado_em": "2026-06-23T10:00:00",
      "atualizado_em": "2026-06-23T10:30:00",
      "itens": [
        {"separado": false, "destino": "EQUINIX SP4", "quantidade": 2,
         "item": "SPF-LX", "tipo": "", "origem": "engenharia",
         "responsavel": "administração", "acao": "Remanejar"}, ...
      ],
      "envios": { "EQUINIX SP4": {"nf": "12345", "data_envio": "2026-06-23"} }
    }

A separação de cada item é a coluna ``separado`` (persistida junto). NF e data
de envio são por **destino** (local), em ``envios``.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

PASTA = Path(__file__).parent / "dados" / "projetos"

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slug(texto: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(texto)).strip("_") or "sem_psc"


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def caminho(psc: str) -> Path:
    return PASTA / f"{_slug(psc)}.json"


def existe(psc: str) -> bool:
    return caminho(psc).exists()


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


def normalizar_item(d: dict) -> dict:
    """Padroniza um dicionário de item (tipos e chaves)."""
    return {
        "separado": bool(d.get("separado", False)),
        "sem_estoque": bool(d.get("sem_estoque", False)),
        "destino": str(d.get("destino", "") or "").strip(),
        "quantidade": _quantidade_int(d.get("quantidade")),
        "item": str(d.get("item", "") or "").strip(),
        "tipo": str(d.get("tipo", "") or "").strip(),
        "serial": str(d.get("serial", "") or "").strip(),
        "origem": str(d.get("origem", "") or "").strip(),
        "responsavel": str(d.get("responsavel", "") or "").strip(),
        "acao": str(d.get("acao", "") or "").strip(),
    }


# ---------------------------------------------------------------------------
# CRUD de projetos
# ---------------------------------------------------------------------------

def salvar(projeto: dict) -> None:
    PASTA.mkdir(parents=True, exist_ok=True)
    projeto["atualizado_em"] = _agora()
    projeto.setdefault("criado_em", projeto["atualizado_em"])
    caminho(projeto["psc"]).write_text(
        json.dumps(projeto, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def carregar(psc: str) -> Optional[dict]:
    p = caminho(psc)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - JSON corrompido
        return None


def excluir(psc: str) -> None:
    p = caminho(psc)
    if p.exists():
        p.unlink()


def listar() -> list[dict]:
    """Todos os projetos salvos (lista de dicts completos), por PSC."""
    PASTA.mkdir(parents=True, exist_ok=True)
    projetos = []
    for arq in sorted(PASTA.glob("*.json")):
        try:
            projetos.append(json.loads(arq.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            continue
    projetos.sort(key=lambda p: str(p.get("psc", "")))
    return projetos


# ---------------------------------------------------------------------------
# Conversões item <-> DataFrame
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
    for c in ("destino", "item", "tipo", "serial", "origem", "responsavel", "acao"):
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
    psc: str, arquivo: str, paginas: int, metodo: str, itens_norm: pd.DataFrame
) -> dict:
    """Monta um projeto novo a partir do DataFrame normalizado da extração."""
    itens = [
        normalizar_item(
            {
                "separado": False,
                "destino": r.get("destino", ""),
                "quantidade": r.get("quantidade"),
                "item": r.get("item", ""),
                "tipo": "",
                "origem": r.get("origem", ""),
                "responsavel": r.get("responsavel", ""),
                "acao": r.get("acao", ""),
            }
        )
        for _, r in itens_norm.iterrows()
    ]
    return {
        "psc": psc,
        "arquivo": arquivo,
        "paginas": paginas,
        "metodo": metodo,
        "criado_em": _agora(),
        "atualizado_em": _agora(),
        "itens": itens,
        "envios": {},
    }
