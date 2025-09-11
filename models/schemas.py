from typing import List, Optional
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import List, Optional

try:
    # Pydantic v1
    from pydantic import BaseModel
    _PYD_V2 = False
except Exception:  # pragma: no cover
    # Fallback import name if environment is Pydantic v2-only naming differs
    from pydantic import BaseModel  # type: ignore
    _PYD_V2 = True

logger = logging.getLogger(__name__)


class Supplier(BaseModel):
    name: Optional[str] = None
    inn: Optional[str] = None
    kpp: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None


class Item(BaseModel):
    article: Optional[str] = None
    description: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    price: Optional[float] = None
    discount: Optional[float] = None
    amount: Optional[float] = None


class Total(BaseModel):
    amount_without_discount: Optional[float] = None
    discount: Optional[float] = None
    amount: Optional[float] = None


class Invoice(BaseModel):
    number: Optional[str] = None
    supplier: Optional[Supplier] = None
    items: Optional[List[Item]] = None
    total: Optional[Total] = None

    class Config:
        extra = 'allow'  # не валим объекты из-за дополнительных ключей


def validate_invoices(obj) -> List[dict]:
    """Проверяет список JSON-ов счетов по схеме. Возвращает только валидные как dict.
    Невалидные пропускаются с предупреждением в логах.
    """
    # Если получен один объект вместо списка, оборачиваем в список
    if isinstance(obj, dict):
        logger.info("Получен один счет как объект, оборачиваем в список")
        obj = [obj]
    elif not isinstance(obj, list):
        logger.warning("Ожидался список счетов от LLM, получено: %s", type(obj).__name__)
        return []

    valids: List[dict] = []
    for idx, item in enumerate(obj):
        try:
            model = Invoice.parse_obj(item)
            valids.append(model.dict(exclude_none=True))
        except Exception as e:
            logger.warning("Невалидный JSON счета на позиции %d: %s", idx, e)
    return valids


@dataclass(frozen=True)
class EmailInfo:
    """Информация о найденном письме для отображения в списке"""
    message_id: str
    subject: str
    date: datetime
    bracket_value: str  # Значение из квадратных скобок
    sender: str
    references: tuple  # Message-IDs предыдущих писем в цепочке (tuple для hashable)
    reply_to: str
    
    def __str__(self):
        # Конвертируем в UTC+05:00 таймзону согласно спецификации
        utc5_timezone = timezone(timedelta(hours=5))
        
        # Если дата уже с таймзоной, конвертируем
        if self.date.tzinfo is not None:
            utc5_date = self.date.astimezone(utc5_timezone)
        else:
            # Если дата наивная (без таймзоны), предполагаем что она в UTC и конвертируем
            utc_date = self.date.replace(tzinfo=timezone.utc)
            utc5_date = utc_date.astimezone(utc5_timezone)
            
        date_str = utc5_date.strftime("%d.%m.%Y %H:%M")
        return f"{date_str} | {self.subject} [{self.bracket_value}]"
