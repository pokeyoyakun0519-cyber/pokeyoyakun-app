from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MISSING = "missing"
VALID_EMPTY = "valid_empty"
VALID = "valid"
CORRUPT = "corrupt"

PRODUCT_LIST_FIELDS = (
    "aliases",
    "source_urls",
    "release_date_history",
    "sites",
)
CANDIDATE_LIST_FIELDS = PRODUCT_LIST_FIELDS + ("candidate_reasons", "retail_hits")
SOURCE_LIST_FIELDS = ("detected_products", "official_changes")


class CorruptJsonError(RuntimeError):
    pass


@dataclass(frozen=True)
class JsonFileResult:
    path: Path
    state: str
    data: Any = None
    error: str = ""
    backup_path: Path | None = None
    backup_valid: bool = False

    @property
    def recoverable(self) -> bool:
        return self.state == CORRUPT and self.backup_valid


def inspect_json_file(
    path: Path,
    expected_type: type,
    *,
    nullable_list_fields: tuple[str, ...] = (),
) -> JsonFileResult:
    path = Path(path)
    backup_path = path.with_suffix(path.suffix + ".bak")
    if not path.exists():
        broken_exists = path.with_suffix(path.suffix + ".broken").exists()
        backup_result = _read_json(backup_path, expected_type, nullable_list_fields)
        if broken_exists or backup_path.exists():
            return JsonFileResult(
                path,
                CORRUPT,
                error="本体がなく、破損痕跡またはバックアップが存在します",
                backup_path=backup_path,
                backup_valid=backup_result.state in {VALID, VALID_EMPTY},
            )
        return JsonFileResult(path, MISSING, backup_path=backup_path)

    result = _read_json(path, expected_type, nullable_list_fields)
    if result.state != CORRUPT:
        return result
    backup_result = _read_json(backup_path, expected_type, nullable_list_fields)
    return JsonFileResult(
        path,
        CORRUPT,
        error=result.error,
        backup_path=backup_path,
        backup_valid=backup_result.state in {VALID, VALID_EMPTY},
    )


def ensure_json_writable(
    path: Path,
    expected_type: type,
    *,
    nullable_list_fields: tuple[str, ...] = (),
) -> None:
    result = inspect_json_file(
        path, expected_type, nullable_list_fields=nullable_list_fields
    )
    if result.state == CORRUPT:
        raise CorruptJsonError(f"破損JSONへの保存を拒否しました: {path}")


def restore_json_backup(
    path: Path,
    expected_type: type,
    *,
    nullable_list_fields: tuple[str, ...] = (),
) -> bool:
    path = Path(path)
    backup_path = path.with_suffix(path.suffix + ".bak")
    backup_result = _read_json(backup_path, expected_type, nullable_list_fields)
    if backup_result.state not in {VALID, VALID_EMPTY}:
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    broken_path = path.with_suffix(path.suffix + ".broken")
    if path.exists() and not broken_path.exists():
        shutil.copy2(path, broken_path)
    temporary = path.with_suffix(path.suffix + ".restore.tmp")
    shutil.copy2(backup_path, temporary)
    temporary.replace(path)
    return True


def _read_json(
    path: Path,
    expected_type: type,
    nullable_list_fields: tuple[str, ...],
) -> JsonFileResult:
    if not path.exists():
        return JsonFileResult(path, MISSING)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return JsonFileResult(path, CORRUPT, error=str(error))
    if not isinstance(data, expected_type):
        return JsonFileResult(
            path,
            CORRUPT,
            error=f"トップレベル型が{expected_type.__name__}ではありません",
        )
    if nullable_list_fields:
        data, error = _normalize_nullable_lists(data, nullable_list_fields)
        if error:
            return JsonFileResult(path, CORRUPT, error=error)
    state = VALID_EMPTY if not data else VALID
    return JsonFileResult(path, state, data=data)


def _normalize_nullable_lists(
    records: list[Any], fields: tuple[str, ...]
) -> tuple[list[dict[str, Any]], str]:
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(records):
        if not isinstance(raw, dict):
            return [], f"項目{index}がobjectではありません"
        record = dict(raw)
        for field in fields:
            if field not in record:
                continue
            value = record[field]
            if value is None:
                record[field] = []
            elif not isinstance(value, list):
                return [], f"項目{index}.{field}がlistまたはnullではありません"
        normalized.append(record)
    return normalized, ""
