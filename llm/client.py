"""Клиент для работы с OpenRouter LLM API."""

import requests
import time
from typing import Optional, Dict, Any, List
from logging_setup import get_logger
import config

logger = get_logger(__name__)


class LLMClient:
    """Клиент для взаимодействия с OpenRouter API."""
    
    def __init__(self, 
                 api_key: Optional[str] = None,
                 base_url: Optional[str] = None,
                 default_model: Optional[str] = None):
        """
        Инициализация клиента LLM.
        
        Args:
            api_key: API ключ OpenRouter
            base_url: Базовый URL API
            default_model: Модель по умолчанию
        """
        self.api_key = api_key or config.API_KEY
        self.base_url = base_url or config.API_BASE_URL
        self.default_model = default_model or config.DEFAULT_MODEL
        
        if not self.api_key:
            raise ValueError("API ключ не задан. Укажите OPENROUTER_API_KEY в конфигурации.")
    
    def query(self, 
              prompt: str, 
              model: Optional[str] = None,
              temperature: float = 0.1,
              timeout: int = 60) -> str:
        """
        Отправляет запрос к LLM и возвращает ответ.
        
        Args:
            prompt: Текст запроса
            model: Модель для использования (если не указана, используется default_model)
            temperature: Температура генерации
            timeout: Таймаут запроса в секундах
            
        Returns:
            Ответ от LLM
            
        Raises:
            RuntimeError: При ошибке сети или API
        """
        use_model = model or self.default_model
        url = f"{self.base_url}/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
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
            logger.debug(f"LLM request -> model={use_model} url={url}")
            response = requests.post(url, headers=headers, json=data, timeout=timeout)
        except requests.RequestException as net_err:
            logger.error(f"OpenRouter network error: {net_err}")
            raise RuntimeError(f"Сетевой сбой при обращении к OpenRouter: {net_err}")
        
        elapsed = time.perf_counter() - start_time
        logger.info(f"LLM запрос выполнен за {elapsed:.2f}с")
        
        if not response.ok:
            error_details = response.text[:1000]
            logger.error(f"Ошибка ответа OpenRouter: HTTP {response.status_code}. URL={url}. Детали: {error_details}")
            raise RuntimeError(f"Ошибка ответа OpenRouter: HTTP {response.status_code}. Детали: {error_details}")
        
        try:
            content = response.json()["choices"][0]["message"]["content"]
            if content is None:
                logger.warning("LLM вернул пустой content")
                return ""
            logger.debug("LLM response parsed successfully")
            return content
        except Exception as parse_err:
            logger.exception("Failed to parse LLM response JSON")
            raise RuntimeError(f"Не удалось распарсить ответ OpenRouter: {parse_err}. Сырое тело: {response.text[:1000]}")
    
    def get_available_models(self, timeout: int = 30) -> List[str]:
        """
        Получает список доступных моделей от OpenRouter.
        
        Args:
            timeout: Таймаут запроса
            
        Returns:
            Список ID моделей
        """
        try:
            url = f"{self.base_url}/models"
            headers = {"Authorization": f"Bearer {self.api_key}"}
            
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
    
    def extract_json_from_response(self, text: str) -> Any:
        """
        Извлекает JSON из ответа LLM, убирая markdown обертки.
        
        Args:
            text: Ответ от LLM
            
        Returns:
            Очищенный JSON текст
        """
        import re
        import json
        
        # Проверяем на None или пустую строку
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
