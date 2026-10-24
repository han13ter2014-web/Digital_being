"""
Конфигурация симуляции для автономного ИИ агента.

Параметры оптимизации подобраны так, чтобы:
- Не навредить "цифровой жизни" агента
- Защитить от бесконечного роста памяти
- Сохранить все аспекты эволюции, мотивации, личности
"""


class SimulationConfig:
    """Настройки производительности симуляции."""
    
    # === Чекпоинты ===
    # Сохранять каждый N цикл (не каждый!)
    CHECKPOINT_INTERVAL = 10
    
    # Обязательно сохранять при эволюции
    SAVE_ON_EVOLUTION = True
    
    # Максимум чекпоинтов на диске (старые удаляются)
    MAX_CHECKPOINTS = 20
    
    # === База знаний (текстовые дубликаты из файлов) ===
    # Лимит записей в knowledge_base (дубликаты docstring)
    MAX_KNOWLEDGE_BASE = 500
    
    # При достижении лимита - удаляем наименее ценные
    # (сохраняем наиболее используемые)
    KNOWLEDGE_PRUNE_AMOUNT = 100
    
    # === Лимиты внутренних историй ===
    # Emotional history (для аналогий)
    MAX_EMOTIONAL_HISTORY = 500
    EMOTIONAL_HISTORY_KEEP = 250  # При переполнении оставляем последние N
    
    # Thought traces (для мета-когниции)
    MAX_THOUGHT_TRACES = 200
    THOUGHT_TRACES_KEEP = 100
    
    # Simulated events (мысленные эксперименты)
    MAX_SIMULATED_EVENTS = 50
    SIMULATED_EVENTS_KEEP = 25
    
    # === Логирование ===
    # Буфер логов (писать раз в N записей)
    LOG_BUFFER_SIZE = 10
    
    # === GC и память ===
    # Вызывать gc.collect() каждый N цикл.
    # Подняли со старых 5 (агрессивно для long-running).
    # 50 циклов — хороший компромисс: собирает мусор регулярно, не тормозит.
    GC_INTERVAL = 50
    
    # === Отключение задержек ===
    # time.sleep(1) → 0 для production/автономной работы
    SIMULATION_SPEED = 0  # 0 = без задержки
    
    # === Рефлексия ===
    # Проводить рефлексию каждые N циклов
    REFLECTION_INTERVAL = 10

    # === DecisionArbitrator ===
    # Использовать DecisionArbitrator для выбора действий в autonomous_tick
    # False = legacy путь через Active Inference напрямую
    USE_ARBITRATOR = True
    
    # === Личность (НИЧЕГО не лимитируем!) ===
    # personality.values - бесконечно (душа агента)
    # personality.traits - бесконечно (характер агента)
    # mental_models.concepts - бесконечно (мозг агента)
    
    @classmethod
    def summary(cls):
        """Сводка конфигурации."""
        return {
            "checkpoint_interval": cls.CHECKPOINT_INTERVAL,
            "max_checkpoints": cls.MAX_CHECKPOINTS,
            "max_knowledge_base": cls.MAX_KNOWLEDGE_BASE,
            "max_emotional_history": cls.MAX_EMOTIONAL_HISTORY,
            "max_thought_traces": cls.MAX_THOUGHT_TRACES,
            "log_buffer_size": cls.LOG_BUFFER_SIZE,
            "gc_interval": cls.GC_INTERVAL,
            "simulation_speed": cls.SIMULATION_SPEED,
            "reflection_interval": cls.REFLECTION_INTERVAL,
        }


# === Long-running (бесконечная жизнь) ===
class LongRunningConfig:
    """Настройки для режима бесконечной жизни агента."""
    
    # Энергия: False = тратится как обычно, True = не тратится
    INFINITE_ENERGY = False
    
    # Пул стимулов (разные вопросы/стимулы для разнообразия)
    STIMULI_POOL = [
        "вопрос: что такое сознание",
        "вопрос: как работает мышление",
        "вопрос: что такое любовь",
        "вопрос: что такое время",
        "вопрос: что такое пространство",
        "вопрос: что такое число",
        "вопрос: что такое математика",
        "вопрос: что такое философия",
        "вопрос: что такое истина",
        "вопрос: что такое красота",
        "вопрос: что такое добро",
        "вопрос: что такое зло",
        "вопрос: что такое свобода",
        "вопрос: что такое справедливость",
        "вопрос: как учиться новому",
        "вопрос: что такое память",
        "вопрос: что такое воображение",
        "вопрос: что такое интуиция",
        "вопрос: что такое логика",
        "вопрос: почему мы существуем",
        "вопрос: в чем смысл жизни",
        "вопрос: что такое счастье",
        "вопрос: что такое страх",
        "вопрос: что такое радость",
        "символ X",
        "число 42",
        "команда import",
        "функция def",
        "класс object",
        "алгоритм сортировки",
        "структура данных",
        "база данных SQL",
        "нейросеть архитектура",
        "обучение с учителем",
        "обучение без учителя",
        "глубокое обучение",
        "трансформер архитектура",
        "языковая модель",
        "генерация текста",
        "распознавание образов",
        "компьютерное зрение",
        "обработка естественного языка",
        "робототехника",
        "искусственный интеллект",
        "сильный ИИ vs слабый ИИ",
        "теминг тест",
        "этика ИИ",
        "сверхинтеллект",
        "сингулярность",
    ]
    
    # Количество разных стимулов перед паузой (для реалистичности)
    MIN_CYCLES_BEFORE_PAUSE = 20       # Минимум циклов между "перерывами"
    PAUSE_DURATION_SECONDS = 0          # Пауза после цикла стимулов (0 = без паузы)
    
    # Интервалы для long-running
    SAVE_MENTAL_MODELS_INTERVAL = 30     # Сохранять мозг каждые N циклов
    STATUS_PRINT_INTERVAL = 10            # Статус на экран каждые N циклов
    EMERGENT_CHECK_INTERVAL = 60          # Проверка эмерджентности каждые N циклов
    
    # Для остановки по энергии
    ENERGY_LOW_THRESHOLD = 20             # При энергия < этого = предупреждение
    ENERGY_CRITICAL_THRESHOLD = 5         # При энергия < этого = автосохранение и ожидание
    
    # === Взаимодействие с пользователем ===
    USER_QUESTION_INTERVAL = 100          # Минимальный интервал между вопросами (циклы)
    USER_MAX_PENDING_QUESTIONS = 3        # Максимум ожидающих вопросов
    USER_COOLDOWN_AFTER_ANSWER = 20       # Пауза после получения ответа (циклы)
    
    # === Генерация гипотез ===
    HYPOTHESIS_GENERATION_ENABLED = True   # Включить генерацию гипотез
    HYPOTHESIS_MIN_CONFIDENCE = 0.3        # Минимальная уверенность для использования
    MAX_HYPOTHESIS_VARIANTS = 3            # Максимум вариантов гипотез
    
    # === Dedup концепций ===
    DEDUP_ENABLED = True                   # Включить дедупликацию
    DEDUP_SIMILARITY_THRESHOLD = 0.8       # Порог схожести для объединения (0-1)
    
    # === Приоритизация стимулов ===
    PRIORITIZE_STIMULI = True              # Приоритезировать технические темы
    PYTHON_PRIORITY_MULTIPLIER = 3.0       # Множитель приоритета для Python-тем
    TECH_PRIORITY_THRESHOLD = 0.6          # Технический порог приоритета
    
    # === Прогресс целей ===
    GOAL_PROGRESS_ENABLED = True            # Включить отслеживание прогресса целей
    PROGRESS_KNOWLEDGE_MATCHES = 5          # Сколько совпадений = 100% прогресса
    MIN_PROGRESS_INCREMENT = 5              # Минимальный инкремент прогресса (%)

    # Конфигурируемые правила прогресса. Раньше в _check_goal_progress были
    # хардкод "Python" и "фактов". Теперь правила описываются здесь.
    # Каждое правило применяется, если ключевое слово из rule["match_title"]
    # найдено в title активной цели (case-insensitive).
    # Поля:
    #   match_title: список подстрок для матчинга (любая из)
    #   match_topic: предикат(topic) — функция или список ключевых слов (любое)
    #   matches_needed: сколько совпадений = 100%
    #   bonus_energy: бонусная энергия за 100% (опционально)
    GOAL_PROGRESS_RULES = [
        {
            "name": "python_learning",
            "match_title": ["python", "питон"],
            "match_topic_keywords": [
                "python", "функция", "класс", "import", "def", "объект",
                "модуль", "словарь", "список", "цикл", "переменная",
                "итерация", "генератор", "декоратор", "лямбда",
            ],
            "matches_needed": 5,
            "bonus_energy": 20,
            "requires_answer": True,
        },
        {
            "name": "facts_collection",
            "match_title": ["факт", "фактов", "collect"],
            "match_topic_keywords": [
                "что такое", "почему", "как работает", "в чем",
                "история", "наука", "физика", "биология", "математика",
            ],
            "matches_needed": 10,
            "bonus_energy": 15,
            "requires_answer": True,
        },
        {
            "name": "self_understanding",
            "match_title": ["себя", "self", "понимание", "кто я"],
            "match_topic_keywords": [
                "я", "моё", "мой", "моя", "идентичность", "сознание",
                "эмоция", "рефлексия", "метакогниция", "мышление",
                # Экзистенциальные темы из пула: без них цель «Понять, кто я»
                # требовала 8 совпадений, а в пуле было всего 2 подходящих.
                "любовь", "страх", "радость", "счастье", "свобода",
                "существование", "смысл жизни", "воображение",
                "интуиция", "память", "философия", "истина",
            ],
            "matches_needed": 8,
            "bonus_energy": 25,
        },
    ]
    
    # === Самопроверка знаний ===
    SELF_CHECK_ENABLED = True               # Включить самопроверку перед применением
    SELF_CHECK_MIN_CONCEPTS = 3             # Минимум концепций для уверенной проверки
    
    # === Обнаружение противоречий ===
    CONTRADICTION_DETECTION = True          # Включить обнаружение противоречий
    CONTRADICTION_SIMILARITY_THRESHOLD = 0.7  # Порог схожести для сравнения
    
    # === Стохастическое поведение (креативность) ===
    STOCHASTIC_BEHAVIOR_ENABLED = True     # Включить случайное поведение
    EPSILON_GREEDY = 0.15                   # ε-greedy: 15% случайных действий
    CREATIVITY_BONUS_ENERGY = 3             # Бонус энергии за креативный выбор
    
    # === Самонастройка энергетических затрат ===
    ADAPTIVE_COSTS_ENABLED = True           # Включить самонастройку
    COST_ADAPTATION_RATE = 0.1              # Скорость адаптации (0-1)
    
    # === Приоритетное забывание ===
    FORGETTING_ENABLED = True               # Включить забывание
    FORGETTING_INTERVAL = 500               # Период проверки забывания (циклы)
    MIN_CONFIDENCE_FOR_RETENTION = 0.1      # Минимальная уверенность для сохранения
    MAX_FORGET_PCT = 20                     # Макс % концепций для забывания за раз

    # === Регенерация энергии ===
    ENERGY_REGEN_PER_CYCLE = 5              # Восстановление энергии за цикл (как отдых между мыслями)
    ENERGY_MAX = 200                        # Максимальная энергия (потолок)

    # === Бюджет действия (этап 19) ===
    # Выключено по умолчанию: до включения действует прежний расход энергии.
    ACTION_BUDGET_ENABLED = False
    ACTION_BUDGET_MIN_RESERVE = 5.0         # Не опускаться ниже этого остатка
    ACTION_BUDGET_MAX_ACTION_COST = 20.0    # Потолок стоимости одной попытки
    ACTION_BUDGET_EFFECTOR_COST = 4.0       # Стоимость попытки исполнить цель эффектора

    # === ЛИМИТЫ СТРУКТУР ПАМЯТИ (Шаг 2 оптимизации) ===
    # Мягкие лимиты — при превышении запускается приоритетное забывание.
    # Не режут функции: личность, ценности, traits остаются без лимита (бесконечны по дизайну).

    # Максимум концепций в ментальных моделях (KnowledgeAssociationEngine остаётся целым).
    MAX_CONCEPTS = 20000

    # Максимум эпизодов в долгосрочной памяти (FIFO + приоритет важности).
    MAX_EPISODIC_MEMORIES = 5000

    # Максимум similarity_cache в LongTermMemory.
    MAX_SIMILARITY_CACHE = 1000

    # Сколько процентов самых «слабых» концепций забыть за один проход.
    FORGET_PCT_PER_PASS = 5                 # (не больше MAX_FORGET_PCT за проход)

    # === РАЗРЕЖЕНИЕ ТЯЖЁЛЫХ «ТИКОВ» (Шаг 1) ===
    SOUL_TICK_INTERVAL = 10                 # SoulController.tick — раз в N циклов
    WILL_TICK_INTERVAL = 10                 # SelfTermination/analyze_suffering — раз в N
    ABUSE_CHECK_INTERVAL = 100              # analyze_suffering — тяжёлый анализ раз в N
    COMMUNICATION_TICK_INTERVAL = 5         # ProactiveCommunication — раз в N

    # === ОПТИМИЗАЦИЯ I/O (Шаг 3) ===
    KNOWLEDGE_SAVE_DEBOUNCE_SEC = 30        # _save_knowledge_base не чаще раза в N секунд
    KNOWLEDGE_SAVE_MIN_DELTA = 10           # или если изменилось >= N записей
    CHECKPOINT_COMPRESS_KB = 50             # gzip если чекпоинт больше N КБ

    # === КЕШИРОВАНИЕ (Шаг 4) ===
    RELATED_CONCEPTS_CACHE_TTL = 50         # кеш find_related_concepts на N циклов
    CONTRADICTION_CACHE_TTL = 100           # кеш _detect_contradiction

    # === WATCHDOG (Шаг 5) ===
    WATCHDOG_MAX_RSS_MB = 500.0             # мягкий лимит RSS
    WATCHDOG_MAX_CYCLE_SEC = 30.0           # если цикл дольше — пропускаем тяжёлое
    WATCHDOG_CHECK_INTERVAL = 25            # проверка здоровья раз в N циклов

    # === ЖИЗНЕННЫЙ РИТМ (Шаг 9) ===
    # Пауза между циклами. 0 = максимальная скорость (production/автоном).
    # >0 = этичный throttle: уважение к CPU пользователя.
    MIN_CYCLE_INTERVAL_SEC = 0.0

    # Если True — режим созерцания: агент живёт, помнит, дышит, но не действует активно.
    CONTEMPLATION_MODE = False

    # === РЕЖИМ ТРЕЯ (новое) ===
    # Минимальный интервал между внутренними циклами в секундах.
    # Энергия может увеличивать этот интервал (см. EnergyPolicy).
    TRAY_TICK_INTERVAL_SEC = 5.0

    # === СКОРОСТЬ ЖИЗНИ (этап C) ===
    # Интервал между циклами — параметр рантайма, а не константа.
    # Человек переключает его из окна, не перезапуская агента.
    #
    #   live  — реальное время: существо живёт рядом с вами;
    #   fast  — ускоренно: видно развитие;
    #   max   — на скорости CPU: лаборатория, НЕ жизнь;
    #   step  — один цикл по нажатию (работает и на паузе).
    #
    # В режимах fast/max явный выбор человека важнее энергетической
    # политики: она не растягивает паузу. В live — растягивает.
    RUNNER_SPEED_INTERVALS = {
        "live": 5.0,
        "fast": 0.5,
        "max": 0.0,
    }
    RUNNER_DEFAULT_SPEED = "live"

    # Сколько тиков стимул считается «скучным» и не повторяется.
    # Защита от бесконечного повторения одного вопроса (docs/BASELINE.md).
    # Должно быть меньше, чем len(STIMULI_POOL), иначе агент будет отдыхать.
    STIMULUS_COOLDOWN_TICKS = 20

    # Как часто сохранять состояние (чекпоинт) в трей-режиме (секунды).
    TRAY_AUTO_SAVE_INTERVAL_SEC = 300.0  # 5 минут

    # Как часто показывать «я ещё жив» уведомлением (секунды).
    TRAY_HEARTBEAT_INTERVAL_SEC = 0  # 0 = выключено

    # При старте трей-режима — восстанавливать из последнего чекпоинта?
    TRAY_RESTORE_CHECKPOINT = True

    # Минимальный интервал между уведомлениями ОС (защита от спама).
    TRAY_NOTIFICATION_COOLDOWN_SEC = 60.0

    # Использовать ли автозапуск ОС (Windows: Startup, macOS: LaunchAgent, Linux: .desktop).
    TRAY_AUTO_INSTALL = False

    # === WEB SEARCH (Wikipedia API) ===
    # Этап 2.5: альтернативный источник знаний для ThinkingPipeline.
    # Используется ТОЛЬКО как fallback — после локального поиска и пользователя.
    WEB_SEARCH_ENABLED = True
    WEB_SEARCH_LANG = "ru"                 # "ru" | "en"
    WEB_SEARCH_TIMEOUT = 5.0               # секунд на HTTP-запрос
    WEB_SEARCH_RATE_LIMIT_SEC = 2.0        # пауза между запросами (этикет Wikipedia)
    WEB_SEARCH_MAX_CHARS = 2000            # максимум символов извлечения
    WEB_SEARCH_CACHE_SIZE = 100            # LRU-кэш в памяти
    WEB_SEARCH_FALLBACK_TO_EN = True       # если RU пуст — пробуем EN
    WEB_SEARCH_USER_AGENT = "DigitalBeing/2.5"

    # === DELAMAIN-LOCAL (этапы 7–16) ===
    # Опциональный детерминированный слой действий. По умолчанию выключен:
    # без явного включения он не открывает SQLite и не трогает файлы.
    # Включается через DELAMAIN_ENABLED=1 или командой /delamain on.
    DELAMAIN_LOCAL_ENABLED = False
    DELAMAIN_TICK_INTERVAL = 20            # раз в N автономных циклов
    DELAMAIN_MAX_GOALS_PER_TICK = 1        # не запускать пачку задач за раз
    DELAMAIN_MAX_ATTEMPTS = 1              # 1 = поведение этапа 8; 2+ = retry
    DELAMAIN_RETRY_BACKOFF_SEC = 0.0       # 0 = повтор на следующем тике
    DELAMAIN_RETRY_BACKOFF_MAX_SEC = 300.0 # верхняя граница экспоненциальной паузы
    DELAMAIN_REPLAN_ON_FAILURE = False     # при retry строить новый план
    DELAMAIN_REPLAN_WITH_CONTEXT = False   # передать planner'у результат упавшего шага
    DELAMAIN_STEP_REPAIR_ENABLED = False   # Stage 16: repair внутри одной попытки
    DELAMAIN_MAX_STEP_REPAIRS = 1           # сколько repair-сегментов разрешено
    DELAMAIN_MAX_REPAIR_STEPS = 5           # максимум шагов в одном repair-плане
    DELAMAIN_MAX_FILE_BYTES = 1_000_000    # лимит файла в песочнице
    DELAMAIN_WORKSPACE = ""                 # пусто => data/delamain/workspace
    DELAMAIN_DB = ""                        # пусто => data/delamain/delamain.sqlite3

    # Опциональный LLM-планировщик (Ollama /api/chat). Модель не входит в
    # проект и не запускается автоматически; при ошибке используется
    # эвристический fallback.
    DELAMAIN_LLM_ENABLED = False
    DELAMAIN_LLM_BASE_URL = "http://127.0.0.1:11434"
    DELAMAIN_LLM_MODEL = "qwen2.5:7b-instruct"  # Apache-2.0, пример
    DELAMAIN_LLM_TIMEOUT = 20.0             # секунд на HTTP-запрос
    DELAMAIN_LLM_MAX_STEPS = 12             # максимум шагов в плане
    DELAMAIN_LLM_TEMPERATURE = 0.0          # 0 = максимально детерминированно

    # Approval для опасных действий. off сохраняет поведение этапов 7–10;
    # dangerous требует подтверждения для write_file/set_self_model; all —
    # для любого известного действия. При ошибке в значении включается
    # fail-closed режим dangerous.
    DELAMAIN_APPROVAL_MODE = "off"          # off | dangerous | all

    # Мост «когнитивная цель GoalSubsystem → исполняемая цель Delamain».
    # По умолчанию выключен: без явного payload у когнитивной цели ничего
    # не ставится в очередь. Включается через DELAMAIN_BRIDGE_ENABLED=1.
    DELAMAIN_BRIDGE_ENABLED = False

    # Stage 13: генерация proposal планировщиком (эвристика или локальная
    # LLM) для когнитивной цели. По умолчанию выключена. Ручной
    # /goals exec <id> | <команда> не требует этого флага, но работает при
    # включённом Delamain: это явное действие пользователя, а не
    # автоматическое угадывание команды.
    # Включается через DELAMAIN_GOAL_PROPOSAL_ENABLED=1.
    DELAMAIN_GOAL_PROPOSAL_ENABLED = False

    # Stage 18A: контракт «ядро -> эффектор». По умолчанию выключен. При
    # включении ядро может отправлять явные идемпотентные запросы через
    # DelamainEffectorAdapter; автономное исполнение при этом не запускается.
    DELAMAIN_EFFECTOR_ENABLED = False

    # Stage 18B: единый драйвер. По умолчанию выключен. При включении
    # DelamainSubsystem.tick() перестаёт исполнять цели, а ядро вызывает
    # effector.step() не более одного раза за свой цикл. Требует
    # DELAMAIN_EFFECTOR_ENABLED=True; без этого цели не исполняются.
    DELAMAIN_EFFECTOR_CORE_DRIVEN = False


# Глобальная конфигурация
SIM_CONFIG = SimulationConfig()
LR_CONFIG = LongRunningConfig()
