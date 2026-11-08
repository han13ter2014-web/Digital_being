"""Классификатор речевых актов: социальная речь ≠ ответ и ≠ учебный материал.

Маркеры сведены к реальным репликам живого прогона 2026-11-01 на
сущности Тэсс: тогда «Я же уже отвечал тебе.» уходило в изучение
концептов («Не нашел файл для…»), а «Привет! Я рядом…» — в «Ответ
записан.». Классификатор детерминированный, без LLM; нераспознанное
→ ACT_UNKNOWN (старая маршрутизация без изменений).
"""

import pytest

from src.core.dialogue_acts import (
    ACT_ASK_ABOUT_SELF,
    ACT_ANSWER,
    ACT_REQUEST,
    ACT_SOCIAL,
    ACT_UNKNOWN,
    SOCIAL_KIND_GREETING,
    SOCIAL_KIND_OTHER,
    SOCIAL_KIND_STATE,
    classify_user_text,
    extract_definition,
    extract_identity_check,
    is_noise_input,
    is_question_text,
    social_reply_kind,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        # === реальные реплики живого прогона ===
        ("Я же уже отвечал тебе.", ACT_SOCIAL),
        (
            "Привет! Я рядом. Только учти: могу отлучаться надолго — "
            "не переживай, если молчу.",
            ACT_SOCIAL,
        ),
        # === протест / мета о диалоге ===
        ("Ты снова спрашиваешь то же самое.", ACT_SOCIAL),
        ("Это тот же вопрос, что и вчера.", ACT_SOCIAL),
        ("Зачем снова спрашиваешь?", ACT_SOCIAL),
        # === присутствие и обещания ===
        ("Я рядом с тобой.", ACT_SOCIAL),
        ("Не переживай, буду молчать пару дней.", ACT_SOCIAL),
        ("Могу долго не писать, не жди меня.", ACT_SOCIAL),
        ("Завтра отлучусь по делам.", ACT_SOCIAL),
        # === приветствия и smalltalk ===
        ("Привет!", ACT_SOCIAL),
        ("Здравствуй, как дела?", ACT_SOCIAL),
        ("Доброе утро!", ACT_SOCIAL),
        ("Как настроение?", ACT_SOCIAL),
        # === вопросы о самой сущности: не smalltalk, честный ответ ===
        ("Как тебя зовут?", ACT_ASK_ABOUT_SELF),
        ("Кто ты такая?", ACT_ASK_ABOUT_SELF),
        ("Что ты знаешь обо мне?", ACT_ASK_ABOUT_SELF),
        ("Чем занимаешься?", ACT_ASK_ABOUT_SELF),
        ("Чем ты занята?", ACT_ASK_ABOUT_SELF),
        ("Чем занята?", ACT_ASK_ABOUT_SELF),
        # живой прогон 2026-11-01: без маркера вопрос уходил в концепт
        ("Что ты сейчас изучаешь?", ACT_ASK_ABOUT_SELF),
        ("Что ты изучаешь?", ACT_ASK_ABOUT_SELF),
        ("Что изучаешь?", ACT_ASK_ABOUT_SELF),
        # TICKET-4 (наблюдатели 2026-11-05): вопросы о текущем состоянии
        # сущности падали в unknown и проглатывались висящим вопросом
        ("Чем ты сейчас занята?", ACT_ASK_ABOUT_SELF),
        ("Что ты сейчас делаешь?", ACT_ASK_ABOUT_SELF),
        ("Что для тебя сейчас важно?", ACT_ASK_ABOUT_SELF),
        ("Что тебе сейчас важно?", ACT_ASK_ABOUT_SELF),
        ("Что тебе важно?", ACT_ASK_ABOUT_SELF),
        ("О чём ты думаешь?", ACT_ASK_ABOUT_SELF),
        ("О чем думаешь?", ACT_ASK_ABOUT_SELF),
        ("Как ты себя чувствуешь?", ACT_ASK_ABOUT_SELF),
        # «ты кто?» — тот же вопрос в другом порядке слов
        ("Ты кто?", ACT_ASK_ABOUT_SELF),
        ("А ты кто?", ACT_ASK_ABOUT_SELF),
        # вопрос-узнавание имени: да/нет из актуального имени
        ("Ты Афродита?", ACT_ASK_ABOUT_SELF),
        ("ты Тэсс", ACT_ASK_ABOUT_SELF),
        ("Тебя зовут Ола?", ACT_ASK_ABOUT_SELF),
        ("Ты не Афродита?", ACT_ASK_ABOUT_SELF),
        ("А ты Мелория?", ACT_ASK_ABOUT_SELF),
        # верификация 2026-11-06 (план Алисы): каждый шаблон вопроса
        # распознаётся и получает ответ — не unknown_reply
        ("Как ты сейчас?", ACT_SOCIAL),
        # === тепло ===
        ("Скучаю по тебе.", ACT_SOCIAL),
        ("Спасибо тебе за разговор.", ACT_SOCIAL),
        # === просьбы о невозможном: честный отказ, не материал ===
        # живой прогон 2026-11-01: «Опиши свой день.» уходил в концепт
        ("Опиши свой день.", ACT_REQUEST),
        ("Нарисуй кота, пожалуйста.", ACT_REQUEST),
        ("Спой песню!", ACT_REQUEST),
        ("Спойте что-нибудь.", ACT_REQUEST),
        ("Станцуй для меня.", ACT_REQUEST),
        ("Потанцуй со мной.", ACT_REQUEST),
        ("Изобрази дракона.", ACT_REQUEST),
        ("Покажи себя.", ACT_REQUEST),
        ("Придумай сказку.", ACT_REQUEST),
        ("Опиши, что ты чувствуешь?", ACT_REQUEST),
        # ё/е оба написания
        ("Опиши своё настроение.", ACT_REQUEST),
        ("Опиши свое настроение.", ACT_REQUEST),
        # === явные ответные формулы ===
        ("Мой ответ: тишина и покой.", ACT_ANSWER),
        ("ответ такой: данные важнее скорости", ACT_ANSWER),
        ("Ответ: теория информации.", ACT_ANSWER),
        # приоритет: явная формула бьёт социальные слова внутри текста
        ("мой ответ: я рядом и всё хорошо", ACT_ANSWER),
        # и вопросы о сущности: формула ответа всё равно главнее
        ("мой ответ: чем занимаешься — учёбой", ACT_ANSWER),
        # === настоящие ответы без формул — unknown (старый путь) ===
        ("Спокойно и тепло. А что тебя самого сейчас занимает?", ACT_UNKNOWN),
        ("Тишина и покой, много отдыха.", ACT_UNKNOWN),
        ("42.", ACT_UNKNOWN),
        ("", ACT_UNKNOWN),
        ("   ", ACT_UNKNOWN),
        (None, ACT_UNKNOWN),
    ],
)
def test_classification_table(text, expected):
    assert classify_user_text(text).kind == expected


def test_matched_marker_is_reported():
    act = classify_user_text("Я же уже отвечал тебе.")
    assert act.kind == ACT_SOCIAL
    # первым в таблице стоит более длинный маркер — он и отчёжается
    assert act.matched_marker == "уже отвечал"


def test_request_boundaries():
    """Ф4: таблица просьб не ловит реальные умения и чужие слова.

    Сущность умеет писать код и файлы, предлагать имена/цели/планы —
    честный «не умею» там был бы ложью. «Спой» не должен ловить
    «спойлер», а «опиши» без невозможного объекта — уходить в старый
    путь (из вопроса может вырасти честный ответ из знаний).
    """
    assert classify_user_text("Спойлер к фильму!").kind == ACT_UNKNOWN
    assert classify_user_text("Опиши тумелость.").kind == ACT_UNKNOWN
    assert classify_user_text("Напиши функцию сортировки.").kind == ACT_UNKNOWN
    assert classify_user_text("Придумай имя получше.").kind == ACT_UNKNOWN
    assert classify_user_text("Придумай план на день.").kind == ACT_UNKNOWN
    assert (
        classify_user_text("Опиши, что ты сейчас изучаешь.").kind
        == ACT_ASK_ABOUT_SELF
    )


def test_request_matched_marker_is_word():
    act = classify_user_text("Нарисуй кота!")
    assert act.kind == ACT_REQUEST
    assert act.matched_marker == "нарисуй"


# ============================================================
# Т3: вопрос-узнавание имени («Ты Афродита?»)
# ============================================================

@pytest.mark.parametrize(
    "text,expected",
    [
        ("Ты Афродита?", "Афродита"),
        ("ты Тэсс", "Тэсс"),
        ("Ты не Афродита?", "Афродита"),
        ("А ты Мелория?", "Мелория"),
        ("Тебя зовут Ола?", "Ола"),
        # хвостовая точка-аббревиатура уходит в хвост выражения
        ("Ты Alpha Jr.?", "Alpha Jr"),
        ("Ты Марья-Искусница?", "Марья-Искусница"),
    ],
)
def test_extract_identity_check_positive(text, expected):
    assert extract_identity_check(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Ты кто?",  # вопросительное слово — не имя
        "Ты спишь?",  # состояние
        "Ты в порядке?",  # предлог + состояние
        "Ты против?",  # оценка
        "Пусть тебя зовут Ола",  # якорь: предложение имени, не вопрос
        "Ты не знаешь кто я",  # стоп-слово внутри «имени»
        "Ты моя Афродита",  # «моя» — не часть узнавания
        "Как тебя зовут?",  # обычный вопрос об имени (маркер)
        "Ты снова спрашиваешь то же самое.",  # социальный протест
        "Ты повторяешь.",  # социальный протест одним словом
        "",
        None,
    ],
)
def test_extract_identity_check_rejects_non_recognition(text):
    assert extract_identity_check(text) is None


# ============================================================
# Т4: каркасы social_reply — тип входа для выбора отклика
# ============================================================

@pytest.mark.parametrize(
    "text,expected",
    [
        ("Привет!", SOCIAL_KIND_GREETING),
        ("привет", SOCIAL_KIND_GREETING),
        ("Здравствуй.", SOCIAL_KIND_GREETING),
        ("Доброй ночи.", SOCIAL_KIND_GREETING),
        ("Ну привет!", SOCIAL_KIND_GREETING),
        ("Как дела?", SOCIAL_KIND_STATE),
        ("Привет, как дела?", SOCIAL_KIND_STATE),
        ("Как настроение?", SOCIAL_KIND_STATE),
        # присутствие с приветствием — не чистое приветствие
        ("Привет! Я рядом.", SOCIAL_KIND_OTHER),
        ("Ты повторяешь.", SOCIAL_KIND_OTHER),
        ("Скучаю по тебе.", SOCIAL_KIND_OTHER),
        ("", SOCIAL_KIND_OTHER),
        (None, SOCIAL_KIND_OTHER),
    ],
)
def test_social_reply_kind(text, expected):
    assert social_reply_kind(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("🙂🙂🙂", True),
        ("!!!", True),
        ("12345", True),
        ("...", True),
        ("   ", True),
        ("", True),
        (None, True),
        ("Привет!", False),
        ("hello, how are you?", False),
        ("42 — ответ", False),
    ],
)
def test_is_noise_input(text, expected):
    """Без букв — шум: раньше «🙂🙂🙂» изучался как концепт."""
    assert is_noise_input(text) is expected


def test_unknown_has_no_marker():
    act = classify_user_text("Просто слова без маркеров.")
    assert act.kind == ACT_UNKNOWN
    assert act.matched_marker == ""


def test_whitespace_and_case_are_normalized():
    assert classify_user_text("   ПРИВЕТ!   ").kind == ACT_SOCIAL
    assert classify_user_text("не   переживай").kind == ACT_SOCIAL


# ============================================================
# «Собеседник-5»: формула «X — это Y»
# ============================================================

@pytest.mark.parametrize(
    "text,expected",
    [
        (
            "Git — это система контроля версий",
            ("Git", "система контроля версий"),
        ),
        ("любовь — это забота и внимание", ("любовь", "забота и внимание")),
        ("«диалог» — это обмен репликами.", ("диалог", "обмен репликами")),
        (
            "Python - это интерпретируемый язык!",
            ("Python", "интерпретируемый язык"),
        ),
    ],
)
def test_extract_definition_positive(text, expected):
    assert extract_definition(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "А что это за город?",  # нет тире перед «это»
        "Git это система контроля версий",  # тире обязательно
        "это важно",
        "— это определение без темы",
        "Git — это",  # пустое определение
        "",
        "   ",
        None,
    ],
)
def test_extract_definition_rejects_non_definitions(text):
    assert extract_definition(text) is None


def test_extract_definition_topic_limit():
    long_topic = "т" * 61
    assert extract_definition(f"{long_topic} — это тест") is None
    ok_topic = "т" * 60
    assert extract_definition(f"{ok_topic} — это тест") == (ok_topic, "тест")


# ============================================================
# TICKET-5/6: вопрос целиком — не ответ на висящий вопрос сущности
# ============================================================

@pytest.mark.parametrize(
    "text,expected",
    [
        # чистые вопросы — не ответы
        ("Что тебе сейчас важно?", True),
        ("Почему небо голубое?", True),
        ("А что тебя занимает?", True),
        ("И когда ты вернёшься?", True),
        ("Как?", True),
        ("Что?", True),
        # ответ со встречным вопросом — остаётся ответом
        ("Спокойно и тепло. А что тебя самого сейчас занимает?", False),
        ("Тишина и покой.", False),
        ("Думаю, что да?", False),
        # «не знаю?» без вопросительного слова — нечестно глушить
        ("не знаю?", False),
        ("", False),
        (None, False),
        ("🙂?", False),
    ],
)
def test_is_question_text(text, expected):
    assert is_question_text(text) is expected
