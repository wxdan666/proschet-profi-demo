"""
Модуль работы с базой данных: модели и управление сессиями.

Используется SQLAlchemy ORM поверх SQLite. Сущности предметной области
ООО «СтройМонтаж»:

- Worker    - сотрудник (монтажник, сварщик, электромонтажник, кладовщик);
- Object    - строительный объект (договор с заказчиком);
- Material  - позиция склада (номенклатура с остатком и учётной ценой);
- Movement  - движение материала: приход, расход на объект, возврат;
- Order     - заявка на работы по объекту с назначенными исполнителями.

Остаток материала хранится в Material.stock и меняется только сервисом
materials через операции движения - так журнал Movement всегда объясняет,
откуда взялось текущее число на складе.
"""
from contextlib import contextmanager
from datetime import date, datetime

from sqlalchemy import (
    Column, Date, DateTime, Float, ForeignKey, Integer, String, Table,
    create_engine, event,
)
from sqlalchemy.engine import URL
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from config import CONFIG
from logger import log

Base = declarative_base()

# Связочная таблица «многие ко многим»: на заявку назначается бригада.
order_workers = Table(
    "order_workers",
    Base.metadata,
    Column("order_id", Integer,
           ForeignKey("orders.id", ondelete="CASCADE"), primary_key=True),
    Column("worker_id", Integer,
           ForeignKey("workers.id", ondelete="CASCADE"), primary_key=True),
)


class Worker(Base):
    """Сотрудник предприятия."""
    __tablename__ = "workers"

    id = Column(Integer, primary_key=True)
    name = Column(String(150), nullable=False)
    specialty = Column(String(100), nullable=False)
    phone = Column(String(30), default="")

    orders = relationship("Order", secondary=order_workers,
                          back_populates="workers")

    def __repr__(self) -> str:
        return f"<Worker id={self.id} name={self.name!r}>"


class Object(Base):
    """Строительный объект: место, куда списываются материалы и работы."""
    __tablename__ = "objects"

    id = Column(Integer, primary_key=True)
    code = Column(String(20), unique=True, nullable=False)
    name = Column(String(150), nullable=False)
    address = Column(String(200), default="")
    customer = Column(String(150), default="")
    contract_sum = Column(Float, default=0.0)
    status = Column(String(30), default="Подготовка", index=True)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)

    movements = relationship("Movement", back_populates="object")
    orders = relationship("Order", back_populates="object")

    def __repr__(self) -> str:
        return f"<Object {self.code} {self.name!r}>"


class Material(Base):
    """Позиция номенклатуры склада."""
    __tablename__ = "materials"

    id = Column(Integer, primary_key=True)
    code = Column(String(20), unique=True, nullable=False)
    name = Column(String(150), nullable=False)
    category = Column(String(60), default="Прочее", index=True)
    unit = Column(String(10), default="шт")
    price = Column(Float, default=0.0)        # учётная цена за единицу
    stock = Column(Float, default=0.0)        # текущий остаток
    min_stock = Column(Float, default=0.0)    # неснижаемый остаток

    movements = relationship("Movement", back_populates="material")

    @property
    def stock_value(self) -> float:
        """Стоимость остатка по учётной цене."""
        return round((self.stock or 0) * (self.price or 0), 2)

    def __repr__(self) -> str:
        return f"<Material {self.code} {self.name!r}>"


class Movement(Base):
    """Строка журнала движения материалов."""
    __tablename__ = "movements"

    KIND_IN = "Приход"
    KIND_OUT = "Расход"
    KIND_RETURN = "Возврат"
    KINDS = (KIND_IN, KIND_OUT, KIND_RETURN)

    id = Column(Integer, primary_key=True)
    doc_date = Column(Date, default=date.today, index=True)
    kind = Column(String(10), nullable=False, index=True)
    material_id = Column(Integer, ForeignKey("materials.id"),
                         nullable=False, index=True)
    object_id = Column(Integer, ForeignKey("objects.id"),
                       nullable=True, index=True)
    qty = Column(Float, nullable=False)
    price = Column(Float, default=0.0)
    doc_number = Column(String(40), default="")
    counterparty = Column(String(150), default="")  # поставщик или получатель
    comment = Column(String(250), default="")
    created_at = Column(DateTime, default=datetime.now)

    material = relationship("Material", back_populates="movements")
    object = relationship("Object", back_populates="movements")

    @property
    def amount(self) -> float:
        return round(self.qty * self.price, 2)


class Order(Base):
    """Заявка на выполнение работ на объекте."""
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    object_id = Column(Integer, ForeignKey("objects.id"),
                       nullable=True, index=True)
    description = Column(String(250), nullable=False)
    status = Column(String(20), default="Новая", index=True)
    total_cost = Column(Float, default=0.0)  # стоимость работ
    created_at = Column(DateTime, default=datetime.now)

    object = relationship("Object", back_populates="orders")
    workers = relationship("Worker", secondary=order_workers,
                           back_populates="orders")

    def __repr__(self) -> str:
        return f"<Order id={self.id} status={self.status!r}>"


# ===== Подключение =====
_DB_CFG = CONFIG["database"]
_url = _DB_CFG["url"]
if _url.startswith("sqlite:///"):
    # Путь к файлу передаётся отдельным полем, а не строкой URL:
    # символы вроде «?» в имени папки иначе читаются как параметры запроса.
    _url = URL.create("sqlite", database=_url[len("sqlite:///"):])
engine = create_engine(
    _url,
    echo=_DB_CFG.get("echo", False),
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):
    """Включить контроль внешних ключей и журнал WAL для SQLite.

    Дополнительно регистрируется функция lower_ru: встроенные LOWER и LIKE
    в SQLite приводят к нижнему регистру только латиницу, и поиск
    «ОСВЕЩЕНИЕ» не находил бы «освещение».
    """
    dbapi_conn.create_function(
        "lower_ru", 1, lambda v: v.lower() if isinstance(v, str) else v,
        deterministic=True)
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")
    cur.close()


Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
log.info("База данных инициализирована: %s", _DB_CFG["url"])


@contextmanager
def session_scope():
    """Открыть сессию на одну операцию.

    При успехе изменения фиксируются, при исключении откатываются,
    сессия закрывается в любом случае. В версии 1.0 приложение работало
    через одну глобальную сессию на всё время жизни процесса - после
    ошибки она оставалась в неопределённом состоянии.
    """
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def reset_database() -> None:
    """Удалить и заново создать все таблицы (для тестов и демо-данных)."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    log.warning("База данных пересоздана")
