from __future__ import annotations

import enum


class PermissionLevel(str, enum.Enum):
    """Уровень риска инструмента.

    SAFE — выполняется автоматически (чтение, поиск, анализ, обычные заметки/задачи).
    CONFIRM — требует подтверждения владельца перед выполнением (отправка сообщений,
        публикация, изменение внешних данных).
    CRITICAL — всегда требует отдельного явного подтверждения (платежи, удаление
        данных, изменение секретов, необратимые операции).
    """

    SAFE = "safe"
    CONFIRM = "confirm"
    CRITICAL = "critical"

    @property
    def requires_confirmation(self) -> bool:
        return self is not PermissionLevel.SAFE
