"""Migração transacional: simula por padrão; use --apply para gravar."""
import argparse
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import sys

from sqlalchemy import select

from .db import make_engine, session_factory
from .models import ImportacaoLegada, Item, Projeto, Remessa
from .schemas import CORES, codigo_projeto
from .services import localidade


class MigrationError(ValueError):
    pass


def texto(value):
    return "" if value is None else str(value).strip()


def boolean(value):
    if value in (True, False, None):
        return bool(value)
    if isinstance(value, str) and value.lower().strip() in ("true", "false", "1", "0", "sim", "não", "nao", ""):
        return value.lower().strip() in ("true", "1", "sim")
    raise MigrationError("Valor booleano inválido; revise separado/sem_estoque.")


def quantidade(value):
    if isinstance(value, bool):
        return None
    try:
        num = Decimal(str(value))
        return int(num) if num.is_finite() and num > 0 and num == num.to_integral_value() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def timestamp(value, warnings):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
        if dt.tzinfo is None:
            # O legado não registrava fuso: não inventar conversão temporal.
            warnings.append("Timestamp legado sem fuso preservado apenas no documento original.")
            return None
        return dt
    except ValueError:
        warnings.append("Timestamp inválido preservado apenas no documento original.")
        return None


def migrar_arquivo(db, path: Path):
    raw = path.read_bytes()
    try:
        original = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeError) as exc:
        raise MigrationError("JSON inválido.") from exc
    if not isinstance(original, dict):
        raise MigrationError("Esperado um objeto de projeto por arquivo.")
    digest = hashlib.sha256(raw).hexdigest()
    if db.scalar(select(ImportacaoLegada.id).where(ImportacaoLegada.sha256 == digest)):
        return {"arquivo": path.name, "resultado": "ja_importado"}
    try:
        codigo = codigo_projeto(texto(original.get("psc")))
    except ValueError as exc:
        raise MigrationError(str(exc)) from exc
    if db.scalar(select(Projeto.id).where(Projeto.codigo == codigo)):
        raise MigrationError(f"{codigo} já existe com conteúdo diferente. Nenhum projeto será sobrescrito.")
    rows = original.get("itens", [])
    envios = original.get("envios", {})
    if not isinstance(rows, list) or not all(isinstance(i, dict) for i in rows):
        raise MigrationError("itens deve ser uma lista de objetos.")
    if not isinstance(envios, dict) or not all(isinstance(v, dict) for v in envios.values()):
        raise MigrationError("envios deve ser um objeto por destino.")
    warnings = []
    p = Projeto(codigo=codigo, arquivo=texto(original.get("arquivo")),
                paginas=quantidade(original.get("paginas")) or 0,
                metodo=texto(original.get("metodo")) or "legado",
                projetista=texto(original.get("autor")),
                responsavel_implantacao=texto(original.get("responsavel_impl")))
    for field in ("criado_em", "atualizado_em"):
        dt = timestamp(original.get(field), warnings)
        if dt:
            setattr(p, field, dt)
    db.add(p)
    db.flush()
    itens = []
    for n, row in enumerate(rows):
        review = []
        loc = localidade(db, texto(row.get("destino")))
        qtd = quantidade(row.get("quantidade"))
        description = texto(row.get("item"))
        if not loc:
            review.append("Destino ausente")
        if qtd is None:
            review.append("Quantidade ausente ou inválida")
        if not description:
            review.append("Descrição ausente")
        separado = boolean(row.get("separado", False))
        sem_estoque = boolean(row.get("sem_estoque", False))
        status = row.get("status")
        if status not in CORES:
            if status:
                review.append("Status legado desconhecido")
            status = "sem_estoque" if sem_estoque else ("separado" if separado else "nao_separado")
        if separado and sem_estoque:
            review.append("Legado marcado separado e sem estoque simultaneamente")
        i = Item(projeto_id=p.id, localidade_id=loc.id if loc else None, ordem=n,
                 descricao=description, quantidade=qtd, status=status,
                 local_origem=texto(row.get("local_origem")), tipo=texto(row.get("tipo")),
                 serial=texto(row.get("serial")), origem=texto(row.get("origem")),
                 responsavel=texto(row.get("responsavel")), acao=texto(row.get("acao")),
                 observacoes=texto(row.get("observacoes")), revisao="; ".join(review))
        db.add(i)
        itens.append(i)
        if review:
            warnings.append(f"Linha {n + 1}: {'; '.join(review)}")
    remessas = 0
    for destino, env in envios.items():
        if not env.get("nf") and not env.get("data_envio"):
            continue
        loc = localidade(db, texto(destino))
        if not loc:
            warnings.append("Envio sem destino preservado apenas no documento original.")
            continue
        data = None
        if env.get("data_envio"):
            try:
                data = date.fromisoformat(str(env["data_envio"]))
            except ValueError:
                warnings.append(f"{destino}: data de envio inválida preservada no original.")
        # JSON antigo não informa quais itens/quantidades foram efetivamente enviados.
        # Não inferir todos os itens como enviados nem juntar NFs pelo número.
        db.add(Remessa(localidade_id=loc.id, status="legado_revisar", nf=texto(env.get("nf")),
                       data_entrega_logistica=data,
                       observacoes=f"Importado de {codigo}. Conferir itens e quantidades do envio legado; original preservado."))
        remessas += 1
        for item in itens:
            if item.localidade_id == loc.id:
                item.revisao = "; ".join(filter(None, [item.revisao, "Conferir envio legado antes de nova remessa"]))
        warnings.append(f"{destino}: NF/data preservadas, sem inferir quantidades enviadas.")
    if not rows:
        warnings.append("Projeto sem itens.")
    db.add(ImportacaoLegada(projeto_id=p.id, sha256=digest, nome_arquivo=path.name,
                           original=original, avisos=warnings))
    db.flush()
    return {"arquivo": path.name, "codigo": codigo, "resultado": "importado", "itens": len(rows),
            "remessas_legadas": remessas, "avisos": warnings}


def migrar_pasta(factory, pasta: Path, apply=False):
    files = sorted(pasta.glob("*.json")) if pasta.is_dir() else []
    if not files:
        raise MigrationError("Pasta inexistente ou sem arquivos JSON. Nenhum dado foi migrado.")
    results = []
    with factory() as db:
        try:
            for path in files:
                try:
                    results.append(migrar_arquivo(db, path))
                except (ValueError, OSError) as exc:
                    raise MigrationError(f"{path.name}: {exc}") from exc
            if apply:
                db.commit()
            else:
                db.rollback()
                for r in results:
                    if r["resultado"] == "importado":
                        r["resultado"] = "simulado"
        except Exception:
            db.rollback()
            raise
    return {"modo": "aplicar" if apply else "simular", "arquivos": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pasta", type=Path)
    parser.add_argument("--apply", action="store_true", help="Gravar; sem esta opção tudo é revertido ao final.")
    args = parser.parse_args()
    try:
        report = migrar_pasta(session_factory(make_engine()), args.pasta, args.apply)
    except Exception as exc:
        # Não imprimir URLs/credenciais presentes em mensagens do driver.
        msg = str(exc) if isinstance(exc, MigrationError) else "Falha no banco. Confira a conexão e execute as migrações de schema."
        print(json.dumps({"erro": msg, "gravado": False}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
