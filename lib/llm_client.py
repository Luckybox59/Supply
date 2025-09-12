"""
Упрощенный клиент для работы с LLM через OpenRouter API.

Простая функциональность без избыточных абстракций.
"""

import requests
import time
import json
import re
from typing import Optional, List, Dict, Any
from logging_setup import get_logger
import config

logger = get_logger(__name__)


def query_llm(prompt: str, model: Optional[str] = None, temperature: float = 0.1, timeout: int = 60) -> str:
    """
    Простой запрос к LLM.
    
    Args:
        prompt: Текст запроса
        model: Модель для использования (по умолчанию из config)
        temperature: Температура генерации
        timeout: Таймаут запроса в секундах
        
    Returns:
        Ответ от LLM
        
    Raises:
        RuntimeError: При ошибке сети или API
    """
    api_key = config.API_KEY
    if not api_key:
        raise RuntimeError("API ключ не задан. Укажите OPENROUTER_API_KEY в конфигурации.")
    
    use_model = model or config.DEFAULT_MODEL
    url = f"{config.API_BASE_URL}/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": getattr(config, "APP_REFERRER", "https://local.parser.app"),
        "X-Title": getattr(config, "APP_TITLE", "ParserGUI"),
    }
    
    data = {
        "model": use_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature
    }
    
    start_time = time.perf_counter()
    
    try:
        logger.debug(f"LLM request -> model={use_model}")
        response = requests.post(url, headers=headers, json=data, timeout=timeout)
    except requests.RequestException as e:
        logger.error(f"OpenRouter network error: {e}")
        raise RuntimeError(f"Сетевой сбой при обращении к OpenRouter: {e}")
    
    elapsed = time.perf_counter() - start_time
    logger.info(f"LLM запрос выполнен за {elapsed:.2f}с")
    
    if not response.ok:
        error_details = response.text[:1000]
        logger.error(f"Ошибка ответа OpenRouter: HTTP {response.status_code}. Детали: {error_details}")
        raise RuntimeError(f"Ошибка ответа OpenRouter: HTTP {response.status_code}. Детали: {error_details}")
    
    try:
        content = response.json()["choices"][0]["message"]["content"]
        if content is None:
            logger.warning("LLM вернул пустой content")
            return ""
        logger.debug("LLM response parsed successfully")
        return content
    except Exception as e:
        logger.error(f"Failed to parse LLM response: {e}")
        raise RuntimeError(f"Не удалось распарсить ответ OpenRouter: {e}")


def extract_invoice_data(text: str, filename: str = "document") -> dict:
    """
    Извлекает данные счета через LLM.
    
    Args:
        text: Текст документа
        filename: Имя файла для контекста
        
    Returns:
        Словарь с извлеченными данными
    """
    prompt = f"""Счет: {filename}
Извлеки из этого текста номер счета, поставщика, список позиций (артикул, наименование, количество, ед., цена, сумма) и итоговую сумму. Верни результат в формате JSON со следующими ключами:
- number (номер счета)
- supplier (объект с ключами name, inn, kpp, address, phone)
- items (массив объектов с ключами article, description, quantity, unit, price, discount, amount)
- total (объект с ключами amount_without_discount, discount, amount)
Текст:
{text}
"""
    
    response = query_llm(prompt)
    return extract_json_from_response(response)


def extract_multiple_documents(documents: List[Dict[str, str]]) -> List[dict]:
    """
    Извлекает данные из нескольких документов одновременно.
    
    Args:
        documents: Список словарей с ключами 'filename' и 'text'
        
    Returns:
        Список словарей с извлеченными данными
    """
    if not documents:
        return []
    
    # Строим промпт для обработки нескольких документов
    prompt_blocks = []
    for i, doc in enumerate(documents):
        filename = doc.get('filename', f'document_{i+1}')
        text = doc.get('text', '')
        
        # Определяем тип документа
        is_application = any(word in filename.lower() for word in ['заявка', 'заявление', 'application'])
        doc_type = "заявка" if is_application else "счет"
        
        template = f"""{doc_type.capitalize()}: {filename}
Извлеки из этого текста номер {doc_type}а, поставщика, список позиций (артикул, наименование, количество, ед., цена, сумма) и итоговую сумму. Верни результат в формате JSON со следующими ключами:
- number (номер {doc_type}а)
- supplier (объект с ключами name, inn, kpp, address, phone)
- items (массив объектов с ключами article, description, quantity, unit, price, discount, amount)
- total (объект с ключами amount_without_discount, discount, amount)
Текст:
{text}
"""
        prompt_blocks.append(template)
    
    header = (
        f"Ниже приведены тексты {len(documents)} документов. Для каждого верни отдельный JSON строго с указанными выше ключами. "
        "Формат ответа: [ { ... }, { ... }, ... ]\n"
    )
    
    full_prompt = header + "\n".join(prompt_blocks)
    response = query_llm(full_prompt)
    
    # Пытаемся извлечь список JSON объектов
    extracted = extract_json_from_response(response)
    if isinstance(extracted, list):
        return extracted
    elif isinstance(extracted, dict):
        return [extracted]
    else:
        logger.warning("Не удалось извлечь структурированные данные из ответа LLM")
        return []


def generate_comparison_report(template_text: str, context: Dict[str, Any]) -> str:
    """
    Генерирует отчет сравнения через LLM.
    
    Args:
        template_text: Текст Jinja2 шаблона
        context: Контекст для шаблона
        
    Returns:
        Сгенерированный Markdown отчет
    """
    ctx_json = json.dumps(context, ensure_ascii=False, indent=2)
    
    prompt = f"""Ты помощник по формированию отчётов. Ниже дан Jinja2-шаблон Markdown и JSON-контекст. 
Сгенерируй финальный Markdown-отчёт строго по шаблону, без дополнительных комментариев.

Важно: при сопоставлении позиций учитывай, что если различия между строками вызваны только явной опечаткой, 
то такие позиции следует считать совпадающими.
Под опечаткой понимаются, в частности: путаница 0/O, 1/l/I, различие регистра, одиночная замена/пропуск/вставка символа, 
замена близких символов (например, русская/латинская буква). Если различие меняет смысл артикула — это уже не совпадение.

Шаблон Jinja2 (Markdown):
````jinja2
{template_text}
````

Контекст JSON:
```json
{ctx_json}
```

Верни только Markdown-результат (без обёрток кода)."""

    return query_llm(prompt)


def get_available_models(timeout: int = 30) -> List[str]:
    """
    Получает список доступных моделей от OpenRouter.
    
    Args:
        timeout: Таймаут запроса
        
    Returns:
        Список ID моделей
    """
    api_key = config.API_KEY
    if not api_key:
        logger.warning("API ключ не задан")
        return []
    
    try:
        url = f"{config.API_BASE_URL}/models"
        headers = {"Authorization": f"Bearer {api_key}"}
        
        response = requests.get(url, headers=headers, timeout=timeout)
        if response.ok:
            data = response.json().get('data', [])
            return [model.get('id', '') for model in data if isinstance(model, dict)]
        else:
            logger.warning(f"Не удалось получить список моделей: HTTP {response.status_code}")
            return []
    except Exception as e:
        logger.warning(f"Ошибка получения списка моделей: {e}")
        return []


def extract_json_from_response(text: str) -> Any:
    """
    Извлекает JSON из ответа LLM, убирая markdown обертки.
    
    Args:
        text: Ответ от LLM
        
    Returns:
        Распарсенный JSON или исходный текст
    """
    if not text:
        logger.warning("Получен пустой ответ от LLM")
        return None
    
    # Удаляем обертку ```json ... ```
    match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return match.group(1)
    
    # Если просто ``` ... ```
    match = re.search(r'```\s*(.*?)\s*```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return match.group(1)
    
    # Если нет обертки, пытаемся парсить как JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Не удалось извлечь JSON из ответа LLM")
        return text