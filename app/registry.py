from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class TokenEntry:
    token: str
    dial_prefix: str


@dataclass(frozen=True)
class CompanyEntry:
    company_id: str
    name: str


def _load_mapping(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        data = yaml.safe_load(text)
    elif suffix == ".json":
        data = json.loads(text)
    else:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError:
            data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: root must be an object")
    return data


def load_token_entries(path: Path) -> dict[str, TokenEntry]:
    data = _load_mapping(path)
    raw_list = data.get("tokens")
    if not isinstance(raw_list, list):
        raise ValueError(f"{path}: expected key 'tokens' with a list")

    by_token: dict[str, TokenEntry] = {}
    for i, item in enumerate(raw_list):
        if not isinstance(item, dict):
            raise ValueError(f"{path}: tokens[{i}] must be an object")
        token = item.get("token")
        prefix = item.get("dial_prefix")
        if not isinstance(token, str) or not token.strip():
            raise ValueError(f"{path}: tokens[{i}].token must be a non-empty string")
        if not isinstance(prefix, str) or len(prefix) != 4 or not prefix.isdigit():
            raise ValueError(
                f"{path}: tokens[{i}].dial_prefix must be a 4-digit string"
            )
        if token in by_token:
            raise ValueError(f"{path}: duplicate token entry")
        by_token[token] = TokenEntry(token=token, dial_prefix=prefix)
    return by_token


def load_company_entries(path: Path) -> dict[str, CompanyEntry]:
    data = _load_mapping(path)
    raw_list = data.get("companies")
    if not isinstance(raw_list, list):
        raise ValueError(f"{path}: expected key 'companies' with a list")

    by_id: dict[str, CompanyEntry] = {}
    for i, item in enumerate(raw_list):
        if not isinstance(item, dict):
            raise ValueError(f"{path}: companies[{i}] must be an object")
        cid = item.get("company_id")
        name = item.get("name")
        if not isinstance(cid, str) or not cid.strip():
            raise ValueError(
                f"{path}: companies[{i}].company_id must be a non-empty string"
            )
        if not isinstance(name, str) or not name.strip():
            raise ValueError(
                f"{path}: companies[{i}].name must be a non-empty string"
            )
        if cid in by_id:
            raise ValueError(f"{path}: duplicate company_id {cid!r}")
        by_id[cid] = CompanyEntry(company_id=cid, name=name.strip())
    return by_id
