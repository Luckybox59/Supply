"""Построитель промптов для LLM."""

from typing import List, Dict, Any


class PromptBuilder:
    """Класс для построения промптов для различных задач LLM."""
    
    # Базовый шаблон для извлечения данных из счета
    INVOICE_TEMPLATE = '''Счет: {filename}
Извлеки из этого текста номер счета, поставщика, список позиций (артикул, наименование, количество, ед., цена, сумма) и итоговую сумму. Верни результат в формате JSON со следующими ключами:
- number (номер счета)
- supplier (объект с ключами name, inn, kpp, address, phone)
- items (массив объектов с ключами article, description, quantity, unit, price, discount, amount)
- total (объект с ключами amount_without_discount, discount, amount)
Текст:
{invoice_text}
'''
    
    @classmethod
    def build_multi_invoice_prompt(cls, invoices: List[Dict[str, str]]) -> str:
        """
        Строит промпт для обработки нескольких счетов одновременно.
        
        Args:
            invoices: Список словарей с ключами 'filename' и 'text'
            
        Returns:
            Готовый промпт для LLM
        """
        if not invoices:
            raise ValueError("Список счетов не может быть пустым")
        
        prompt_blocks = []
        for i, invoice in enumerate(invoices):
            filename = invoice.get('filename', 'unknown')
            text = invoice.get('text', '')
            
            # Проверяем, является ли это заявкой (по индексу или имени файла)
            if i == 0 and len(invoices) == 2:
                # Первый документ может быть заявкой
                doc_type = "заявка" if any(word in filename.lower() for word in ['заявка', 'заявление', 'application']) else "документ"
            else:
                doc_type = "счет"
            
            template = f'''{doc_type.capitalize()}: {filename}
Извлеки из этого текста номер {doc_type}а, поставщика, список позиций (артикул, наименование, количество, ед., цена, сумма) и итоговую сумму. Верни результат в формате JSON со следующими ключами:
- number (номер {doc_type}а)
- supplier (объект с ключами name, inn, kpp, address, phone)
- items (массив объектов с ключами article, description, quantity, unit, price, discount, amount)
- total (объект с ключами amount_without_discount, discount, amount)
Текст:
{text}
'''
            prompt_blocks.append(template)
        
        header = (
            f"Ниже приведены тексты {len(invoices)} документов. Для каждого верни отдельный JSON строго с указанными выше ключами. "
            "Формат ответа: [ { ... }, { ... }, ... ]\n"
        )
        
        return header + "\n".join(prompt_blocks)
    
    @classmethod
    def build_comparison_report_prompt(cls,
                                       template_text: str,
                                       context: Dict[str, Any]) -> str:
        """
        Строит промпт для генерации отчета сравнения через LLM.
        
        Args:
            template_text: Текст Jinja2 шаблона
            context: Словарь контекста для шаблона (любой структуры, например
                     {'app_name': ..., 'inv_name': ..., 'matches': [...], 'only_in_app': [...], 'only_in_inv': [...]} )
        
        Returns:
            Промпт для генерации отчета
        """
        import json
        
        ctx_json = json.dumps(context, ensure_ascii=False, indent=2)
        
        return f"""Ты помощник по формированию отчётов. Ниже дан Jinja2-шаблон Markdown и JSON-контекст. 
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
    
    @classmethod
    def build_single_invoice_prompt(cls, filename: str, text: str) -> str:
        """
        Строит промпт для обработки одного счета.
        
        Args:
            filename: Имя файла
            text: Текст документа
            
        Returns:
            Промпт для LLM
        """
        return cls.INVOICE_TEMPLATE.format(filename=filename, invoice_text=text)
