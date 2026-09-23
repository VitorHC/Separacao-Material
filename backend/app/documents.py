"""Adaptador dos extratores existentes para conferência na interface React."""
import base64
from functools import lru_cache
from pathlib import Path
import sys
from threading import Lock

from fastapi import HTTPException

LEGACY = Path(__file__).resolve().parents[2] / "separador_materiais"
if str(LEGACY) not in sys.path:
    sys.path.insert(0, str(LEGACY))

# Os leitores de OCR são compartilhados por processo e usados sem concorrência.
_extraction_lock = Lock()


@lru_cache(maxsize=1)
def ocr_reader():
    from extracao_imagem import criar_leitor
    return criar_leitor()


@lru_cache(maxsize=1)
def docling_reader():
    from extracao import criar_conversor
    return criar_conversor()


def extrair_documento(nome: str, conteudo: bytes):
    from extracao import ErroExtracao, _extrair_numero_psc, extrair
    from extracao_docx import extrair_tabela_doc, extrair_tabela_docx
    from extracao_imagem import extrair_tabela_imagem, extrair_tabela_texto
    from normalizacao import normalizar_tabela
    import pandas as pd

    ext = Path(nome).suffix.lower()
    if ext not in (".pdf", ".docx", ".doc"):
        raise HTTPException(422, "Use um arquivo PDF, DOCX ou DOC.")
    if not conteudo:
        raise HTTPException(422, "O documento está vazio.")
    try:
        with _extraction_lock:
            if ext == ".docx":
                res = extrair_tabela_docx(conteudo, nome)
            elif ext == ".doc":
                res = extrair_tabela_doc(conteudo, nome)
            else:
                try:
                    res = extrair_tabela_texto(conteudo, nome)
                except ErroExtracao:
                    try:
                        res = extrair_tabela_imagem(conteudo, nome, ocr_reader())
                    except (ErroExtracao, ImportError):
                        try:
                            res = extrair(conteudo, nome, docling_reader())
                        except ImportError as exc:
                            raise HTTPException(503, "O leitor de imagens não está disponível. Configure os componentes de OCR no servidor ou utilize um DOCX com tabela editável.") from exc
        norm = normalizar_tabela(res.df)
        rows = []
        for df, revisar in ((norm.itens, False), (norm.revisar, True)):
            for _, row in df.iterrows():
                rows.append({
                    "destino": str(row.get("destino", "")),
                    "descricao": str(row.get("item", "")),
                    "quantidade": None if pd.isna(row.get("quantidade")) else int(row["quantidade"]),
                    "status": "nao_separado", "tipo": "", "serial": "", "local_origem": "",
                    "origem": str(row.get("origem", "")),
                    "responsavel": str(row.get("responsavel", "")),
                    "acao": str(row.get("acao", "")), "observacoes": "",
                    "revisao": "Confira destino, material e quantidade." if revisar else "",
                })
        return {"codigo": res.numero_psc or _extrair_numero_psc(Path(nome).stem) or "",
                "arquivo": Path(nome).name, "paginas": res.paginas, "metodo": res.metodo,
                "aviso": res.aviso or "Confira todos os materiais com o documento original antes de salvar.",
                "itens": rows,
                "imagem_png": base64.b64encode(res.imagem_png).decode() if res.imagem_png else None}
    except HTTPException:
        raise
    except ErroExtracao as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(422, "Não foi possível ler o documento. Confira o formato e a disponibilidade dos leitores no servidor.") from exc
