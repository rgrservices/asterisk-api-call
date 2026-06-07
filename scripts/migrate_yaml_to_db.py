#!/usr/bin/env python3
"""
Script de migração one-shot: YAML → SQLite

Lê os arquivos tokens.yaml e companies.yaml antigos e cria as tabelas
no banco SQLite, agrupando tudo sob um "Cliente Padrão" por dial_prefix.

Uso:
    python scripts/migrate_yaml_to_db.py [--db call_api.db] [--tokens tokens.yaml] [--companies companies.yaml]

O script é idempotente: tokens já existentes (mesmo hash) são ignorados.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Adiciona a raiz do projeto ao PYTHONPATH para importar app.*
sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml  # noqa: E402

from app.crud import hash_token  # noqa: E402
from app.database import create_db_engine, create_session_factory, init_db  # noqa: E402
from app.models import Client, ClientToken, Company  # noqa: E402


def load_yaml(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: root deve ser um objeto YAML")
    return data


def migrate(db_path: str, tokens_path: Path, companies_path: Path) -> None:
    print(f"Banco de dados: {db_path}")
    engine = create_db_engine(db_path)
    init_db(engine)
    session_factory = create_session_factory(engine)
    db = session_factory()

    try:
        tokens_data = load_yaml(tokens_path)
        companies_data = load_yaml(companies_path)

        raw_tokens: list[dict] = tokens_data.get("tokens", [])
        raw_companies: list[dict] = companies_data.get("companies", [])

        # Agrupa tokens por dial_prefix para criar um cliente por prefixo
        prefixes: dict[str, list[dict]] = {}
        for item in raw_tokens:
            prefix = item.get("dial_prefix", "0000")
            prefixes.setdefault(prefix, []).append(item)

        # Cria ou reutiliza um cliente por dial_prefix
        prefix_to_client: dict[str, Client] = {}
        for prefix, token_items in prefixes.items():
            client_name = f"Cliente Migrado (prefixo {prefix})"
            existing = db.query(Client).filter(Client.dial_prefix == prefix).first()
            if existing:
                client = existing
                print(f"  Cliente existente: {client.name} (id={client.id})")
            else:
                client = Client(name=client_name, dial_prefix=prefix)
                db.add(client)
                db.flush()
                print(f"  Cliente criado: {client.name} (id={client.id})")
            prefix_to_client[prefix] = client

            # Cria tokens
            for item in token_items:
                raw = item.get("token", "")
                label = item.get("label", raw[:12] + "…" if len(raw) > 12 else raw)
                token_hash = hash_token(raw)
                dup = db.query(ClientToken).filter(ClientToken.token_hash == token_hash).first()
                if dup:
                    print(f"    Token já existe, ignorando: {label}")
                    continue
                tok = ClientToken(
                    client_id=client.id,
                    token_hash=token_hash,
                    label=label,
                )
                db.add(tok)
                print(f"    Token criado: {label}")

        db.flush()

        # Associa todas as empresas ao primeiro cliente (ou ao único)
        default_client = next(iter(prefix_to_client.values())) if prefix_to_client else None

        if default_client is None:
            # Sem tokens: cria cliente padrão genérico
            default_client = Client(name="Cliente Padrão", dial_prefix="0000")
            db.add(default_client)
            db.flush()
            print("  Cliente padrão criado (sem tokens no YAML)")

        for item in raw_companies:
            cid = item.get("company_id", "")
            name = item.get("name", cid)
            dup = (
                db.query(Company)
                .filter(Company.company_id == cid, Company.client_id == default_client.id)
                .first()
            )
            if dup:
                print(f"  Empresa já existe, ignorando: {cid}")
                continue
            company = Company(client_id=default_client.id, company_id=cid, name=name)
            db.add(company)
            print(f"  Empresa criada: {cid} → {name} (cliente id={default_client.id})")

        db.commit()
        print("\nMigração concluída com sucesso.")
        print("Revise os clientes na interface administrativa (/admin/) e redistribua as empresas se necessário.")

    except Exception as exc:
        db.rollback()
        print(f"ERRO: {exc}")
        sys.exit(1)
    finally:
        db.close()
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Migra YAML legado para SQLite")
    parser.add_argument("--db", default="call_api.db", help="Caminho do banco SQLite")
    parser.add_argument(
        "--tokens",
        default="examples/tokens.example.yaml",
        help="Caminho do tokens.yaml",
    )
    parser.add_argument(
        "--companies",
        default="examples/companies.example.yaml",
        help="Caminho do companies.yaml",
    )
    args = parser.parse_args()

    migrate(
        db_path=args.db,
        tokens_path=Path(args.tokens),
        companies_path=Path(args.companies),
    )


if __name__ == "__main__":
    main()
