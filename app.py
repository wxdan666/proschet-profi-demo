"""
Главный модуль веб-приложения «ПросчётПрофи» - учёт материалов
и работ на строительных объектах ООО «СтройМонтаж».

Интерфейс построен на Streamlit. Бизнес-логика вынесена в пакет
services/, модуль содержит только разметку страниц и обработку форм.

Запуск:
    streamlit run app.py
"""
import os
from datetime import date

import pandas as pd
import streamlit as st

from config import BASE_DIR, CONFIG
from logger import log
from services import (
    analytics, auth, backup, importer, materials, objects, orders, reports,
    workers,
)
from services.materials import StockError

APP = CONFIG["app"]
ICON = os.path.join(BASE_DIR, APP.get("icon_path", ""))

st.set_page_config(
    page_title=f"{APP['name']} · {APP['organization']}",
    page_icon=ICON if os.path.exists(ICON) else None,
    layout=APP.get("page_layout", "wide"),
)

ACCENT = "#E8620C"
st.markdown(f"""
<style>
.block-container {{ padding-top: 3.6rem; }}
h1, h2, h3 {{ letter-spacing: -0.01em; }}
[data-testid="stSidebar"] .brand {{ font-size: 26px; font-weight: 800;
    color: #FFFFFF; line-height: 1.1; }}
[data-testid="stSidebar"] .brand span {{ color: {ACCENT}; }}
[data-testid="stSidebar"] .org {{ color: #9AA0A6; font-size: 13px;
    margin-top: 4px; }}
[data-testid="stSidebar"] div[role="radiogroup"] label {{
    padding: 10px 12px; border-radius: 8px; margin-bottom: 4px;
    border: 1px solid transparent; transition: background .15s; }}
[data-testid="stSidebar"] div[role="radiogroup"] label:hover {{
    background: rgba(255,255,255,.06); }}
[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) {{
    background: rgba(232,98,12,.16); border-color: rgba(232,98,12,.55); }}
[data-testid="stMetric"] {{ background: #FFFFFF; border: 1px solid #E2E4E1;
    border-left: 4px solid {ACCENT}; border-radius: 8px; padding: 14px 16px; }}
[data-testid="stMetricValue"] {{ font-size: 1.55rem; }}
[data-testid="InputInstructions"] {{ display: none; }}
[data-testid="stDeployButton"] {{ display: none; }}
[data-testid="stSidebar"] .side-foot {{ color: #6B7178; font-size: 12px;
    margin-top: 28px; line-height: 1.5; }}
.eyebrow {{ color: {ACCENT}; font-weight: 700; font-size: 12px;
    letter-spacing: .12em; text-transform: uppercase; margin-bottom: -6px; }}
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def _startup_backup():
    """Ежедневная резервная копия базы — один раз на запуск программы."""
    try:
        return backup.auto_backup()
    except Exception as e:  # noqa: BLE001
        log.error("Не удалось создать резервную копию: %s", e)
        return None


_startup_backup()


# ===== Вспомогательные функции =====
def rub(x: float) -> str:
    """1234567.8 -> '1 234 567,80 ₽'."""
    return f"{x:,.2f} ₽".replace(",", " ").replace(".", ",")


def qty(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def title(eyebrow: str, text: str) -> None:
    st.markdown(f'<div class="eyebrow">{eyebrow}</div>', unsafe_allow_html=True)
    st.header(text)


def download(df: pd.DataFrame, label: str, file_name: str, sheet: str,
             report_title: str, key: str) -> None:
    try:
        st.download_button(label, reports.dataframe_to_xlsx(df, sheet, report_title),
                           file_name=file_name, mime=reports.XLSX_MIME, key=key,
                           icon=":material/download:")
    except Exception as e:
        log.error("Ошибка экспорта %s: %s", file_name, e)
        st.error("Не удалось сформировать файл, подробности в журнале.")


def pin_gate(section: str) -> bool:
    """PIN-доступ к служебным разделам."""
    if not auth.is_section_protected(section):
        return True
    key = f"auth_ok_{section}"
    if st.session_state.get(key):
        if st.sidebar.button(f"Закрыть раздел «{section}»", key=f"out_{section}"):
            st.session_state[key] = False
            st.rerun()
        return True
    st.subheader(f"Раздел «{section}» защищён PIN-кодом")
    with st.form(f"pin_{section}"):
        pin = st.text_input("PIN (4 цифры)", type="password", max_chars=4)
        if st.form_submit_button("Войти", type="primary"):
            ok, msg = auth.check_pin_limited(pin)
            if ok:
                st.session_state[key] = True
                st.rerun()
            else:
                st.error(msg)
    return False


def object_label(o) -> str:
    return f"{o.code} · {o.name}"


def material_label(m) -> str:
    return f"{m.code} · {m.name} (остаток {qty(m.stock)} {m.unit})"


# ===== Меню =====
st.sidebar.markdown(
    f'<div class="brand">Просчёт<span>Профи</span></div>'
    f'<div class="org">{APP["organization"]} · версия {APP["version"]}</div>',
    unsafe_allow_html=True)
st.sidebar.markdown("")

MENU = {
    "Обзор": ":material/dashboard:",
    "Объекты": ":material/apartment:",
    "Склад": ":material/inventory_2:",
    "Заявки на работы": ":material/assignment:",
    "Отчёты": ":material/analytics:",
    "Персонал": ":material/groups:",
    "Импорт из Excel": ":material/upload_file:",
    "Сервис": ":material/settings_backup_restore:",
}
choice = st.sidebar.radio("Разделы", list(MENU), label_visibility="collapsed",
                          format_func=lambda x: f"{MENU[x]}  {x}")
st.sidebar.markdown(
    f'<div class="side-foot">Учёт материалов и работ на объектах<br>'
    f'{date.today():%d.%m.%Y}</div>', unsafe_allow_html=True)


# ===== ОБЗОР =====
if choice == "Обзор":
    title("Сводка на " + date.today().strftime("%d.%m.%Y"), "Обзор")
    d = analytics.dashboard()
    c = st.columns(5)
    c[0].metric("Объектов в работе", d["objects_active"])
    c[1].metric("Стоимость остатков", rub(d["stock_value"]))
    c[2].metric("Расход за месяц", rub(d["month_consumption"]))
    c[3].metric("Ниже минимума", d["low_stock"],
                help="Позиции, остаток которых меньше неснижаемого")
    c[4].metric("Открытых заявок", d["orders_open"])

    left, right = st.columns([3, 2])
    with left:
        st.subheader("Расход материалов на объекты по месяцам")
        months = analytics.consumption_by_month()
        if months:
            st.bar_chart(pd.DataFrame(months).set_index("Месяц"), color=ACCENT,
                         height=280)
        else:
            st.info("Списаний на объекты пока нет.")
    with right:
        st.subheader("Нужно докупить")
        low = materials.low_stock()
        if low:
            st.dataframe(pd.DataFrame([{
                "Материал": m.name, "Остаток": m.stock, "Минимум": m.min_stock,
                "Ед.": m.unit} for m in low]), hide_index=True, width="stretch",
                height=280)
        else:
            st.success("Все остатки выше минимума.")

    st.subheader("Объекты")
    summ = pd.DataFrame(objects.objects_summary())
    if not summ.empty:
        st.dataframe(summ.drop(columns=["id"]), hide_index=True, width="stretch",
                     column_config={
                         c: st.column_config.NumberColumn(format="localized")
                         for c in ("Договор, ₽", "Материалы, ₽", "Работы, ₽",
                                   "Маржа, ₽")})


# ===== ОБЪЕКТЫ =====
elif choice == "Объекты":
    title("Учёт по объектам", "Объекты")
    tab_card, tab_new = st.tabs(["Карточка объекта", "Новый объект"])

    with tab_card:
        f_status = st.segmented_control(
            "Статус", ["Все"] + objects.STATUSES, default="Все")
        objs = objects.list_objects(f_status or "Все")
        if not objs:
            st.info("Объектов с таким статусом нет.")
        else:
            obj = st.selectbox("Объект", objs, format_func=object_label)
            econ = objects.economics(obj.id)
            st.caption(f"{obj.address} · заказчик: {obj.customer or '—'} · "
                       f"сроки: {obj.start_date:%d.%m.%Y} - {obj.end_date:%d.%m.%Y}"
                       if obj.start_date and obj.end_date else obj.address)
            m = st.columns(4)
            m[0].metric("Сумма договора", rub(econ["Договор, ₽"]))
            m[1].metric("Материалы", rub(econ["Материалы, ₽"]))
            m[2].metric("Работы", rub(econ["Работы, ₽"]))
            m[3].metric("Маржа", rub(econ["Маржа, ₽"]),
                        delta=f"{econ['Маржа, %']}%",
                        delta_color="normal" if econ["Маржа, ₽"] >= 0 else "inverse")

            st.subheader("Расход материалов по объекту")
            rep = pd.DataFrame(objects.material_report(obj.id))
            if rep.empty:
                st.info("На объект ещё не списано ни одной позиции.")
            else:
                st.dataframe(rep, hide_index=True, width="stretch",
                             column_config={"Сумма, ₽": st.column_config.NumberColumn(
                                 format="localized")})
                download(rep, "Отчёт о расходе материалов (Excel)",
                         f"Расход_{obj.code}.xlsx", "Расход",
                         f"Отчёт о расходе материалов по объекту {obj.code} "
                         f"«{obj.name}»", key="obj_rep")

            st.subheader("Заявки на работы")
            ol = orders.list_orders(obj.id)
            if ol:
                st.dataframe(pd.DataFrame([{
                    "№": o.id, "Работы": o.description, "Статус": o.status,
                    "Бригада": ", ".join(w.name.split()[0] for w in o.workers) or "—",
                    "Стоимость, ₽": o.total_cost} for o in ol]),
                    hide_index=True, width="stretch")
            else:
                st.caption("Заявок нет.")

            with st.expander("Изменить статус и сумму договора"):
                with st.form("obj_edit"):
                    c1, c2 = st.columns(2)
                    new_status = c1.selectbox("Статус", objects.STATUSES,
                                              index=objects.STATUSES.index(obj.status))
                    new_sum = c2.number_input("Сумма договора, ₽", min_value=0.0,
                                              value=float(obj.contract_sum), step=1000.0)
                    if st.form_submit_button("Сохранить", type="primary"):
                        try:
                            objects.update_object(obj.id, status=new_status,
                                                  contract_sum=new_sum)
                            st.success("Сохранено.")
                            st.rerun()
                        except ValueError as e:
                            st.error(str(e))

    with tab_new:
        with st.form("obj_new", clear_on_submit=True):
            c1, c2 = st.columns([1, 3])
            code = c1.text_input("Код", placeholder="С-26-040")
            name = c2.text_input("Наименование объекта")
            address = st.text_input("Адрес")
            c1, c2, c3 = st.columns(3)
            customer = c1.text_input("Заказчик")
            csum = c2.number_input("Сумма договора, ₽", min_value=0.0, step=1000.0)
            status = c3.selectbox("Статус", objects.STATUSES)
            c1, c2 = st.columns(2)
            d1 = c1.date_input("Начало работ", value=None, format="DD.MM.YYYY")
            d2 = c2.date_input("Окончание", value=None, format="DD.MM.YYYY")
            if st.form_submit_button("Создать объект", type="primary"):
                try:
                    o = objects.create_object(code, name, address, customer, csum,
                                              status, d1, d2)
                    st.success(f"Объект {o.code} создан.")
                except ValueError as e:
                    st.error(str(e))


# ===== СКЛАД =====
elif choice == "Склад":
    title("Материальный учёт", "Склад")
    t_stock, t_in, t_out, t_ret, t_log, t_ref = st.tabs(
        ["Остатки", "Приход", "Списание на объект", "Возврат с объекта",
         "Журнал движения", "Номенклатура"])

    with t_stock:
        c1, c2 = st.columns([3, 2])
        q = c1.text_input("Поиск по наименованию или артикулу",
                          placeholder="например, кабель или МП-002")
        cat = c2.selectbox("Категория", ["Все"] + CONFIG["material_categories"])
        mats = materials.list_materials(q, cat)
        if mats:
            df = pd.DataFrame([{
                "Артикул": m.code, "Наименование": m.name, "Категория": m.category,
                "Ед.": m.unit, "Остаток": m.stock, "Мин.": m.min_stock,
                "Цена, ₽": m.price, "Сумма, ₽": m.stock_value,
            } for m in mats])

            def _low(row):
                bad = row["Мин."] > 0 and row["Остаток"] < row["Мин."]
                return ["background-color: #FDE8DC" if bad else ""] * len(row)

            st.dataframe(df.style.apply(_low, axis=1).format(
                {"Цена, ₽": "{:,.2f}", "Сумма, ₽": "{:,.2f}", "Остаток": "{:g}",
                 "Мин.": "{:g}"}, thousands=" ", decimal=","),
                hide_index=True, width="stretch", height=480)
            st.caption(f"Позиций: {len(df)} · на сумму {rub(df['Сумма, ₽'].sum())}. "
                       "Оранжевым выделены позиции ниже неснижаемого остатка.")
            download(df, "Ведомость остатков (Excel)",
                     f"Остатки_{date.today():%d.%m.%Y}.xlsx", "Остатки",
                     f"Ведомость остатков материалов на {date.today():%d.%m.%Y}",
                     key="stock_xlsx")
        else:
            st.info("Ничего не найдено.")

    with t_in:
        mats = materials.list_materials()
        with st.form("receive", clear_on_submit=True):
            m = st.selectbox("Материал", mats, format_func=material_label)
            c1, c2, c3 = st.columns(3)
            q_in = c1.number_input("Количество", min_value=0.0, step=1.0)
            p_in = c2.number_input("Цена за единицу, ₽", min_value=0.0, step=1.0,
                                   value=float(m.price) if m else 0.0)
            d_in = c3.date_input("Дата", value=date.today(), format="DD.MM.YYYY")
            c1, c2 = st.columns(2)
            doc = c1.text_input("Накладная (УПД) №")
            supplier = c2.text_input("Поставщик")
            if st.form_submit_button("Оприходовать", type="primary"):
                try:
                    materials.receive(m.id, q_in, p_in, doc, supplier, d_in)
                    st.success(f"Принято: {m.name} - {qty(q_in)} {m.unit}.")
                except ValueError as e:
                    st.error(str(e))

    with t_out:
        objs = objects.active_objects()
        mats = [m for m in materials.list_materials() if m.stock > 0]
        if not objs:
            st.warning("Нет объектов, открытых для списания.")
        else:
            with st.form("write_off", clear_on_submit=True):
                obj = st.selectbox("Объект", objs, format_func=object_label)
                m = st.selectbox("Материал", mats, format_func=material_label)
                c1, c2, c3 = st.columns(3)
                q_out = c1.number_input("Количество", min_value=0.0, step=1.0)
                doc = c2.text_input("Требование №")
                d_out = c3.date_input("Дата", value=date.today(), format="DD.MM.YYYY")
                receiver = st.selectbox(
                    "Получил", [w.name for w in workers.list_workers()],
                    index=None, placeholder="Выберите сотрудника")
                if st.form_submit_button("Списать на объект", type="primary"):
                    try:
                        materials.write_off(m.id, obj.id, q_out, doc, receiver or "", d_out)
                        st.success(f"Списано на {obj.code}: {m.name} - "
                                   f"{qty(q_out)} {m.unit}.")
                    except StockError as e:
                        st.error(str(e))
                    except ValueError as e:
                        st.error(str(e))

    with t_ret:
        objs = objects.list_objects()
        mats = materials.list_materials()
        with st.form("return", clear_on_submit=True):
            obj = st.selectbox("С объекта", objs, format_func=object_label)
            m = st.selectbox("Материал", mats, format_func=lambda x: f"{x.code} · {x.name}")
            c1, c2 = st.columns(2)
            q_ret = c1.number_input("Количество", min_value=0.0, step=1.0)
            doc = c2.text_input("Документ №")
            if st.form_submit_button("Вернуть на склад", type="primary"):
                try:
                    materials.return_stock(m.id, obj.id, q_ret, doc)
                    st.success("Возврат оформлен.")
                except ValueError as e:
                    st.error(str(e))

    with t_log:
        c1, c2, c3, c4 = st.columns(4)
        kind = c1.selectbox("Операция", ["Все", "Приход", "Расход", "Возврат"])
        objs = objects.list_objects()
        f_obj = c2.selectbox("Объект", [None] + objs,
                             format_func=lambda o: "Все" if o is None else o.code)
        d_from = c3.date_input("С", value=date(date.today().year, 1, 1),
                               format="DD.MM.YYYY")
        d_to = c4.date_input("По", value=date.today(), format="DD.MM.YYYY")
        mv = materials.list_movements(kind, f_obj.id if f_obj else None,
                                      date_from=d_from, date_to=d_to)
        if mv:
            df = pd.DataFrame([{
                "Дата": x.doc_date.strftime("%d.%m.%Y"), "Операция": x.kind,
                "Документ": x.doc_number, "Материал": x.material.name,
                "Кол-во": x.qty, "Ед.": x.material.unit, "Цена, ₽": x.price,
                "Сумма, ₽": x.amount, "Объект": x.object.code if x.object else "",
                "Поставщик / получатель": x.counterparty,
            } for x in mv])
            st.dataframe(df, hide_index=True, width="stretch", height=460,
                         column_config={c: st.column_config.NumberColumn(
                             format="localized") for c in ("Цена, ₽", "Сумма, ₽")})
            download(df, "Журнал в Excel", "Журнал_движения.xlsx", "Журнал",
                     f"Журнал движения материалов {d_from:%d.%m.%Y} - {d_to:%d.%m.%Y}",
                     key="log_xlsx")
        else:
            st.info("Операций за период нет.")

    with t_ref:
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Новая позиция")
            with st.form("mat_new", clear_on_submit=True):
                a, b = st.columns([1, 2])
                code = a.text_input("Артикул")
                name = b.text_input("Наименование")
                a, b, c = st.columns(3)
                category = a.selectbox("Категория", CONFIG["material_categories"])
                unit = b.selectbox("Ед. изм.", CONFIG["units"])
                min_s = c.number_input("Мин. остаток", min_value=0.0, step=1.0)
                price = st.number_input("Учётная цена, ₽", min_value=0.0, step=1.0)
                if st.form_submit_button("Добавить", type="primary"):
                    try:
                        materials.add_material(code, name, category, unit, price, min_s)
                        st.success("Позиция добавлена. Остаток вносится приходом.")
                    except ValueError as e:
                        st.error(str(e))
        with c2:
            st.subheader("Изменить позицию")
            mats = materials.list_materials()
            m = st.selectbox("Позиция", mats, format_func=lambda x: f"{x.code} · {x.name}")
            if m:
                with st.form("mat_edit"):
                    name = st.text_input("Наименование", m.name)
                    a, b = st.columns(2)
                    cats = CONFIG["material_categories"]
                    category = a.selectbox("Категория", cats,
                                           index=cats.index(m.category) if m.category in cats else 0)
                    units = CONFIG["units"]
                    unit = b.selectbox("Ед. изм.", units,
                                       index=units.index(m.unit) if m.unit in units else 0)
                    a, b = st.columns(2)
                    price = a.number_input("Учётная цена, ₽", min_value=0.0,
                                           value=float(m.price))
                    min_s = b.number_input("Мин. остаток", min_value=0.0,
                                           value=float(m.min_stock))
                    st.caption(f"Остаток {qty(m.stock)} {m.unit} меняется только "
                               "приходом, списанием и возвратом.")
                    if st.form_submit_button("Сохранить", type="primary"):
                        try:
                            materials.update_material(m.id, name, category, unit,
                                                      price, min_s)
                            st.success("Сохранено.")
                            st.rerun()
                        except ValueError as e:
                            st.error(str(e))


# ===== ЗАЯВКИ =====
elif choice == "Заявки на работы":
    title("Работы бригад", "Заявки на работы")
    objs = objects.list_objects()
    c1, c2, c3 = st.columns([3, 2, 2])
    q = c1.text_input("Поиск по описанию")
    st_f = c2.selectbox("Статус", ["Все"] + orders.STATUSES)
    ob_f = c3.selectbox("Объект", [None] + objs,
                        format_func=lambda o: "Все" if o is None else o.code)
    found = orders.search_orders(q, st_f, ob_f.id if ob_f else None)
    colors = {"Новая": "#6B7280", "В работе": "#1D4ED8",
              "Выполнена": "#15803D", "Отменена": "#B91C1C"}
    if found:
        df = pd.DataFrame([{
            "№": o.id, "Объект": o.object.code if o.object else "—",
            "Работы": o.description, "Статус": o.status,
            "Бригада": ", ".join(w.name for w in o.workers) or "—",
            "Стоимость, ₽": o.total_cost} for o in found])
        st.dataframe(df.style.map(lambda v: f"color: {colors.get(v, '')}; font-weight: 600"
                                  if v in colors else "", subset=["Статус"])
                     .format({"Стоимость, ₽": "{:,.2f}"}, thousands=" ", decimal=","),
                     hide_index=True, width="stretch")
        download(df, "Заявки в Excel", "Заявки.xlsx", "Заявки",
                 "Реестр заявок на работы", key="orders_xlsx")
    else:
        st.info("Заявок по условиям не найдено.")

    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        st.subheader("Новая заявка")
        with st.form("order_new", clear_on_submit=True):
            o_obj = st.selectbox("Объект", objects.active_objects(),
                                 format_func=object_label)
            text = st.text_area("Состав работ", height=80)
            cost = st.number_input("Стоимость работ, ₽", min_value=0.0, step=1000.0)
            if st.form_submit_button("Создать", type="primary"):
                try:
                    orders.create_order(text, o_obj.id if o_obj else None, cost)
                    st.success("Заявка создана.")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
    with c2, st.container(border=True):
        st.subheader("Назначить бригаду и статус")
        all_o = orders.list_orders()
        if all_o:
            cur = st.selectbox("Заявка", all_o,
                               format_func=lambda o: f"№{o.id} · {o.description[:60]}")
            staff = workers.list_workers()
            names = {f"{w.name} ({w.specialty})": w.id for w in staff}
            current = [f"{w.name} ({w.specialty})" for w in cur.workers]
            team = st.multiselect("Бригада", list(names), default=current,
                                  key=f"team_{cur.id}")
            a, b = st.columns(2)
            stt = a.selectbox("Статус", orders.STATUSES,
                              index=orders.STATUSES.index(cur.status),
                              key=f"st_{cur.id}")
            price = b.number_input("Стоимость, ₽", min_value=0.0,
                                   value=float(cur.total_cost), key=f"pr_{cur.id}")
            if st.button("Сохранить заявку", type="primary"):
                if orders.update_order(cur.id, stt, price, [names[t] for t in team]):
                    st.success("Заявка обновлена.")
                    st.rerun()
                else:
                    st.error("Не удалось сохранить, подробности в журнале.")


# ===== ОТЧЁТЫ =====
elif choice == "Отчёты":
    title("Анализ расхода", "Отчёты")
    c1, c2 = st.columns(2)
    d_from = c1.date_input("Период с", value=date.today().replace(day=1, month=9),
                           format="DD.MM.YYYY")
    d_to = c2.date_input("по", value=date.today(), format="DD.MM.YYYY")
    by_cat = pd.DataFrame(analytics.consumption_by_category(d_from, d_to))
    top = pd.DataFrame(analytics.top_materials(d_from, d_to))
    summ = pd.DataFrame(objects.objects_summary())
    left, right = st.columns(2)
    with left:
        st.subheader("Расход по категориям")
        if not by_cat.empty:
            st.bar_chart(by_cat.set_index("Категория"), color=ACCENT,
                         horizontal=True, height=320)
    with right:
        st.subheader("Десять самых затратных позиций")
        if not top.empty:
            st.dataframe(top, hide_index=True, width="stretch", height=320,
                         column_config={"Сумма, ₽": st.column_config.NumberColumn(
                             format="localized")})
    st.subheader("Себестоимость и маржа объектов")
    if not summ.empty:
        st.dataframe(summ.drop(columns=["id"]), hide_index=True, width="stretch")
        book = reports.sheets_to_xlsx(
            {"Объекты": summ.drop(columns=["id"]), "Категории": by_cat,
             "Топ-позиции": top},
            {"Объекты": "Себестоимость и маржа объектов",
             "Категории": f"Расход по категориям {d_from:%d.%m.%Y} - {d_to:%d.%m.%Y}",
             "Топ-позиции": "Самые затратные позиции за период"})
        st.download_button("Скачать сводный отчёт (Excel)", book,
                           file_name=f"Сводный_отчёт_{d_to:%d.%m.%Y}.xlsx",
                           mime=reports.XLSX_MIME, type="primary",
                           icon=":material/download:")


# ===== ПЕРСОНАЛ =====
elif choice == "Персонал":
    title("Служебный раздел", "Персонал")
    if pin_gate("Персонал"):
        staff = workers.list_workers()
        if staff:
            st.dataframe(pd.DataFrame([{
                "ФИО": w.name, "Должность": w.specialty, "Телефон": w.phone}
                for w in staff]), hide_index=True, width="stretch")
        c1, c2 = st.columns(2)
        with c1, st.container(border=True):
            st.subheader("Добавить сотрудника")
            with st.form("w_new", clear_on_submit=True):
                n = st.text_input("ФИО")
                s_ = st.text_input("Должность")
                ph = st.text_input("Телефон")
                if st.form_submit_button("Добавить", type="primary"):
                    try:
                        workers.hire_worker(n, s_, ph)
                        st.success("Сотрудник добавлен.")
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))
        with c2, st.container(border=True):
            st.subheader("Удалить из справочника")
            if staff:
                w = st.selectbox("Сотрудник", staff, format_func=lambda x: x.name)
                if st.button("Удалить"):
                    if workers.fire_worker(w.id):
                        st.success("Удалено.")
                        st.rerun()


# ===== ИМПОРТ =====
elif choice == "Импорт из Excel":
    title("Перенос данных", "Импорт из Excel")
    if pin_gate("Импорт"):
        st.write("Загрузите рабочие таблицы. Тип определяется по имени файла: "
                 "**сотрудники**, **объекты**, **материалы** (ведомость остатков), "
                 "**приход**, **расход**. Файлы обрабатываются в правильном порядке, "
                 "повторная загрузка не задваивает документы.")
        files = st.file_uploader("Файлы .xlsx", type=["xlsx"],
                                 accept_multiple_files=True)
        if files and st.button("Импортировать", type="primary"):
            order = [k for k, _ in importer.IMPORT_ORDER]
            queue = []
            for f in files:
                kind, func = importer.detect_kind(f.name)
                if func is None:
                    st.warning(f"{f.name}: тип файла не распознан, пропущен.")
                else:
                    queue.append((order.index(kind), f, func))
            for _, f, func in sorted(queue, key=lambda x: x[0]):
                try:
                    r = func(f)
                    box = st.success if r.ok else st.warning
                    box(f"{f.name} - {r.summary()}")
                    for e in r.errors[:20]:
                        st.caption(e)
                except ValueError as e:
                    st.error(f"{f.name}: {e}")


# ===== СЕРВИС: резервные копии =====
elif choice == "Сервис":
    title("Сопровождение", "Сервис")
    if pin_gate("Сервис"):
        st.write("Резервная копия базы создаётся автоматически при первом запуске "
                 f"программы за день. Хранятся последние {backup.KEEP} копий в папке "
                 "backups рядом с программой.")
        c1, c2 = st.columns([1, 3])
        if c1.button("Создать копию сейчас", type="primary",
                     icon=":material/backup:"):
            path = backup.create_backup("manual")
            st.success(f"Копия создана: {os.path.basename(path)}")
        items = backup.list_backups()
        if items:
            st.dataframe(pd.DataFrame([{
                "Файл": b["file"], "Создана": b["created"].strftime("%d.%m.%Y %H:%M"),
                "Размер, КБ": b["size_kb"]} for b in items]),
                hide_index=True, width="stretch")
            last = items[0]
            with open(last["path"], "rb") as fh:
                c2.download_button("Скачать последнюю копию", fh.read(),
                                   file_name=last["file"],
                                   icon=":material/download:")
            st.subheader("Восстановление из копии")
            pick = st.selectbox("Копия", [b["file"] for b in items])
            sure = st.checkbox("Понимаю, что текущие данные будут заменены данными копии "
                               "(текущее состояние сохранится отдельной копией)")
            if st.button("Восстановить", disabled=not sure):
                try:
                    before = backup.restore_backup(pick)
                    st.success("База восстановлена. Состояние до восстановления "
                               f"сохранено в {os.path.basename(before)}.")
                except ValueError as e:
                    st.error(str(e))
        else:
            st.info("Резервных копий пока нет.")
