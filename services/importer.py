"""
Импорт данных из Excel-выгрузок предприятия.

До внедрения системы учёт в ООО «СтройМонтаж» вёлся в отдельных
таблицах Excel: справочник материалов с остатками, журнал приходных
накладных, журнал требований на выдачу материалов на объекты,
список объектов и сотрудников. Модуль переносит эти таблицы в базу.

Особенности рабочих таблиц, которые учитывает импорт:
- над шапкой бывают строки с названием организации и датой -
  строка заголовков ищется автоматически;
- названия столбцов пишутся по-разному («Ед. изм.», «ед.изм», «Ед»)
  и сравниваются после нормализации;
- повторный импорт того же файла не задваивает данные: приход и расход
  узнаются по номеру документа и артикулу.

Каждая функция возвращает ImportResult со счётчиками и списком ошибок
с номерами строк, как их видит пользователь в Excel.
"""
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional

import pandas as pd
from sqlalchemy import select

from database import Movement, session_scope
from logger import log
from services import materials, objects, workers


@dataclass
class ImportResult:
    title: str
    added: int = 0
    updated: int = 0
    skipped: int = 0
    errors: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        return (f"{self.title}: добавлено {self.added}, обновлено {self.updated}, "
                f"пропущено {self.skipped}, ошибок {len(self.errors)}")


# Синонимы столбцов: каноническое имя -> варианты в рабочих таблицах.
COLUMNS: Dict[str, tuple] = {
    "code": ("артикул", "код", "кодматериала", "кодобъекта", "шифр"),
    "name": ("наименование", "материал", "наименованиематериала",
             "наименованиеобъекта"),
    "category": ("категория", "группа"),
    "unit": ("едизм", "ед", "единица", "единицаизмерения"),
    "price": ("цена", "ценазаед", "ценаруб", "учетнаяцена"),
    "stock": ("остаток", "количество", "колво", "остатокнаначало"),
    "min_stock": ("миностаток", "минимальныйостаток", "неснижаемыйостаток"),
    "date": ("дата", "датадокумента"),
    "doc": ("накладная", "номернакладной", "требование", "номертребования",
            "документ", "номердокумента"),
    "supplier": ("поставщик",),
    "object": ("объект", "объекткод", "шифробъекта"),
    "receiver": ("получил", "получатель", "выдано"),
    "comment": ("примечание", "комментарий"),
    "address": ("адрес",),
    "customer": ("заказчик",),
    "contract": ("суммадоговора", "договор", "суммадоговораруб"),
    "status": ("статус", "состояние"),
    "start": ("начало", "датаначала", "начаторабот"),
    "end": ("окончание", "датаокончания", "срококончания"),
    "fio": ("фио", "сотрудник"),
    "position": ("должность", "специальность"),
    "phone": ("телефон",),
}


def _norm(s) -> str:
    """'Ед. изм.' -> 'едизм', 'Кол-во' -> 'колво', 'Цена, руб.' -> 'ценаруб'."""
    s = str(s).lower().replace("ё", "е")
    return re.sub(r"[^a-zа-я0-9]", "", s)


def read_table(source, must_have: tuple) -> pd.DataFrame:
    """Прочитать первый лист и найти строку шапки.

    :param source: путь к файлу или файловый объект (загрузка из браузера).
    :param must_have: канонические имена столбцов, по которым узнаётся шапка.
    :return: DataFrame со столбцами, переименованными в канонические имена,
             и служебным столбцом _row - номер строки в Excel.
    """
    raw = pd.read_excel(source, header=None, dtype=object)
    for i in range(min(len(raw), 15)):
        cells = [_norm(c) for c in raw.iloc[i].tolist() if pd.notna(c)]
        found = {canon for canon in must_have
                 if any(c in COLUMNS[canon] for c in cells)}
        if found == set(must_have):
            header_idx = i
            break
    else:
        raise ValueError(
            "Не найдена строка заголовков. Ожидались столбцы: "
            + ", ".join(COLUMNS[c][0] for c in must_have))

    rename, used = {}, set()
    for col_pos, cell in enumerate(raw.iloc[header_idx].tolist()):
        key = _norm(cell) if pd.notna(cell) else ""
        for canon, variants in COLUMNS.items():
            if key in variants and canon not in used:
                rename[col_pos] = canon
                used.add(canon)
                break
    # Дата документа из строк над шапкой: «Ведомость остатков на 01.09.2026».
    doc_date = None
    for i in range(header_idx):
        for c in raw.iloc[i].tolist():
            m = re.search(r"(\d{2}\.\d{2}\.\d{4})", str(c))
            if m and doc_date is None:
                doc_date = datetime.strptime(m.group(1), "%d.%m.%Y").date()
    df = raw.iloc[header_idx + 1:].rename(columns=rename)
    df = df[[c for c in df.columns if isinstance(c, str)]].copy()
    df["_row"] = range(header_idx + 2, header_idx + 2 + len(df))
    # Пустые строки и строки «Итого» пропускаем.
    # Строка считается данными, только если заполнены ключевые столбцы:
    # так отсекаются подписи («Кладовщик ____») под таблицей.
    first = must_have[0]
    for key in must_have:
        df = df[df[key].notna()]
    df = df[~df[first].astype(str).str.lower().str.startswith("итого")]
    df.attrs["doc_date"] = doc_date
    return df


def _val(row, key, default=""):
    v = row.get(key, default)
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return default
    return v.strip() if isinstance(v, str) else v


def _to_date(v) -> Optional[date]:
    if v in ("", None) or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y"):
        try:
            return datetime.strptime(str(v).strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"не распознана дата «{v}»")


def _to_float(v, field_name: str) -> float:
    if isinstance(v, str):
        v = v.replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return float(v)
    except (TypeError, ValueError):
        raise ValueError(f"в поле «{field_name}» не число: «{v}»")


def _code(v) -> str:
    """Артикулы вида 101 Excel хранит как 101.0 - приводим к строке."""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


# ===== Импорт отдельных таблиц =====
def import_materials(source) -> ImportResult:
    """Справочник материалов с остатками на дату ввода.

    Новая позиция заводится с нулевым остатком, а остаток вносится
    приходом «Ввод начальных остатков» - так журнал объясняет число
    на складе с первого дня.
    """
    res = ImportResult("Справочник материалов")
    df = read_table(source, ("code", "name"))
    for _, row in df.iterrows():
        n = row["_row"]
        try:
            code = _code(row["code"])
            name = str(_val(row, "name"))
            category = _val(row, "category", "Прочее") or "Прочее"
            unit = _val(row, "unit", "шт") or "шт"
            price = _to_float(_val(row, "price", 0) or 0, "цена")
            stock = _to_float(_val(row, "stock", 0) or 0, "остаток")
            min_stock = _to_float(_val(row, "min_stock", 0) or 0, "мин. остаток")
            existing = materials.find_by_code(code)
            if existing:
                materials.update_material(existing.id, name, category, unit,
                                          existing.price or price, min_stock)
                res.updated += 1
                continue
            m = materials.add_material(code, name, category, unit, price,
                                       min_stock)
            if stock > 0:
                materials.receive(m.id, stock, price, doc_number="ВНО",
                                  supplier="Ввод начальных остатков",
                                  doc_date=_to_date(_val(row, "date", None))
                                  or df.attrs.get("doc_date") or date.today())
            res.added += 1
        except ValueError as e:
            res.errors.append(f"строка {n}: {e}")
    log.info(res.summary())
    return res


def import_objects(source) -> ImportResult:
    res = ImportResult("Объекты")
    df = read_table(source, ("code", "name"))
    for _, row in df.iterrows():
        n = row["_row"]
        try:
            code = _code(row["code"])
            if objects.find_by_code(code):
                res.skipped += 1
                continue
            objects.create_object(
                code=code, name=str(_val(row, "name")),
                address=str(_val(row, "address")),
                customer=str(_val(row, "customer")),
                contract_sum=_to_float(_val(row, "contract", 0) or 0,
                                       "сумма договора"),
                status=_val(row, "status", "Подготовка") or "Подготовка",
                start_date=_to_date(_val(row, "start", None)),
                end_date=_to_date(_val(row, "end", None)),
            )
            res.added += 1
        except ValueError as e:
            res.errors.append(f"строка {n}: {e}")
    log.info(res.summary())
    return res


def import_workers(source) -> ImportResult:
    res = ImportResult("Сотрудники")
    df = read_table(source, ("fio", "position"))
    for _, row in df.iterrows():
        n = row["_row"]
        try:
            name = str(_val(row, "fio"))
            if workers.find_by_name(name):
                res.skipped += 1
                continue
            workers.hire_worker(name, str(_val(row, "position")),
                                str(_val(row, "phone")))
            res.added += 1
        except ValueError as e:
            res.errors.append(f"строка {n}: {e}")
    log.info(res.summary())
    return res


def _movement_exists(kind: str, doc: str, material_id: int) -> bool:
    if not doc:
        return False
    with session_scope() as s:
        return s.scalar(select(Movement.id).where(
            Movement.kind == kind, Movement.doc_number == doc,
            Movement.material_id == material_id)) is not None


def import_receipts(source) -> ImportResult:
    """Журнал приходных накладных."""
    res = ImportResult("Приход материалов")
    df = read_table(source, ("code", "price"))
    for _, row in df.iterrows():
        n = row["_row"]
        try:
            m = materials.find_by_code(_code(row["code"]))
            if m is None:
                raise ValueError(f"артикул {_code(row['code'])} нет в справочнике")
            doc = str(_val(row, "doc"))
            if _movement_exists(Movement.KIND_IN, doc, m.id):
                res.skipped += 1
                continue
            materials.receive(
                m.id, _to_float(_val(row, "stock"), "количество"),
                _to_float(_val(row, "price"), "цена"),
                doc_number=doc, supplier=str(_val(row, "supplier")),
                doc_date=_to_date(_val(row, "date", None)),
                comment=str(_val(row, "comment")),
            )
            res.added += 1
        except ValueError as e:
            res.errors.append(f"строка {n}: {e}")
    log.info(res.summary())
    return res


def import_issues(source) -> ImportResult:
    """Журнал требований: выдача материалов на объекты.

    Строки обрабатываются в порядке дат, чтобы остаток проверялся так же,
    как он менялся на складе в действительности.
    """
    res = ImportResult("Расход на объекты")
    df = read_table(source, ("object", "code"))
    if "date" in df.columns:
        df["_d"] = df["date"].apply(lambda v: _to_date(v) or date.today())
        df = df.sort_values(["_d", "_row"])
    for _, row in df.iterrows():
        n = row["_row"]
        try:
            m = materials.find_by_code(_code(row["code"]))
            if m is None:
                raise ValueError(f"артикул {_code(row['code'])} нет в справочнике")
            obj = objects.find_by_code(_code(row["object"]))
            if obj is None:
                raise ValueError(f"объект {_code(row['object'])} не найден")
            doc = str(_val(row, "doc"))
            if _movement_exists(Movement.KIND_OUT, doc, m.id):
                res.skipped += 1
                continue
            materials.write_off(
                m.id, obj.id, _to_float(_val(row, "stock"), "количество"),
                doc_number=doc, receiver=str(_val(row, "receiver")),
                doc_date=_to_date(_val(row, "date", None)),
                comment=str(_val(row, "comment")),
            )
            res.added += 1
        except ValueError as e:
            res.errors.append(f"строка {n}: {e}")
    log.info(res.summary())
    return res


# Порядок важен: справочники раньше документов движения.
IMPORT_ORDER = (
    ("сотрудник", import_workers),
    ("объект", import_objects),
    ("материал", import_materials),
    ("приход", import_receipts),
    ("расход", import_issues),
)


# Порядок распознавания по имени файла: сначала документы движения,
# потому что «Расход_на_объекты» содержит и слово «объект».
_DETECT = ("приход", "расход", "материал", "объект", "сотрудник")


def detect_kind(filename: str):
    """Определить тип выгрузки по имени файла."""
    low = filename.lower()
    funcs = dict(IMPORT_ORDER)
    for key in _DETECT:
        if key in low:
            return key, funcs[key]
    return None, None


def import_folder(path: str) -> List[ImportResult]:
    """Импортировать все распознанные .xlsx из папки в правильном порядке."""
    files = [f for f in os.listdir(path)
             if f.lower().endswith(".xlsx") and not f.startswith("~$")]
    results = []
    for key, func in IMPORT_ORDER:
        for f in sorted(files):
            if detect_kind(f)[0] == key:
                r = func(os.path.join(path, f))
                r.title = f"{r.title} ({f})"
                results.append(r)
    return results
