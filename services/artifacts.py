from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Set, List

# Простой процессный реестр созданных файлов (относительные пути к текущей рабочей папке)
_ARTIFACTS: Set[str] = set()


def _to_rel(path: str | os.PathLike) -> str:
    p = Path(path)
    try:
        return str(p.resolve().relative_to(Path.cwd().resolve()))
    except Exception:
        # Если путь за пределами cwd — храним как есть
        return str(p)


def register(path: str | os.PathLike):
    """Регистрирует созданный файл. Вызывать ПОСЛЕ успешной записи файла."""
    rel = _to_rel(path)
    _ARTIFACTS.add(rel)


def discard(path: str | os.PathLike):
    """Удаляет запись из реестра (если файл удалён вручную)."""
    rel = _to_rel(path)
    _ARTIFACTS.discard(rel)


def list_all() -> List[str]:
    return sorted(_ARTIFACTS)


def clear():
    _ARTIFACTS.clear()


def cleanup(delete_missing_ok: bool = True) -> dict:
    """Удаляет все зарегистрированные файлы. Возвращает статистику.
    Формат: {"deleted": [...], "not_found": [...], "errors": [(path, err_str), ...]}
    После успешной очистки очищает реестр.
    """
    deleted: List[str] = []
    not_found: List[str] = []
    errors: List[tuple[str, str]] = []

    for rel in list_all():
        p = Path(rel)
        try:
            if p.exists():
                p.unlink()
                deleted.append(rel)
            else:
                if delete_missing_ok:
                    not_found.append(rel)
                else:
                    errors.append((rel, "missing"))
        except Exception as e:
            errors.append((rel, str(e)))
    clear()
    return {"deleted": deleted, "not_found": not_found, "errors": errors}
