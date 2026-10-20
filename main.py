import os
import json
import sys
import io
import random
import time
from datetime import datetime
from src.core.agent import DigitalBeing
from config.simulation_config import SIM_CONFIG, LR_CONFIG
from src.core.buffered_logger import flush_logs, get_logger
from src.perception.user_interaction import UserPromptHandler
from src.core.subsystems import NamingDialogue

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def get_latest_checkpoint(agent_name):
    """Загружает последний checkpoint для агента если существует.

    Делегирует в agent_runner.get_latest_checkpoint (единый источник правды).
    Оставлено в main.py для обратной совместимости.
    """
    from src.core.agent_runner import get_latest_checkpoint as _glc
    return _glc(agent_name)


def print_status_banner(agent, cycle):
    """Печатает статус агента (каждые N циклов)."""
    goals_status = agent.get_goals_status()
    mm_status = agent.get_mental_models_status()
    ui_status = agent.user_interaction
    
    print(f"\n{'='*60}")
    print(f"  🤖 [{agent.name}] Цикл {cycle} | Интеллект: {agent.intelligence} | Энергия: {agent.energy:.0f}")
    print(f"  📚 Концепций: {mm_status['total_concepts']} | Уверенность: {mm_status['concepts_with_high_confidence']}")
    active_title = goals_status['active'][:30] if len(goals_status['active']) > 30 else goals_status['active']
    print(f"  📋 Цели: {goals_status['completed']}/{goals_status['total']} | Активная: {active_title}...")
    if ui_status.pending_questions:
        print(f"  ❓ Ожидают ответа: {len(ui_status.pending_questions)} вопрос(ов)")
    print(f"{'='*60}")


def prompt_user_for_answer(agent, cycle_count: int) -> bool:
    """Запрашивает у пользователя ответ на вопрос агента или команду.
    
    Возвращает:
        True - если пользователь ответил на вопрос агента
        "__EXIT__" - если пользователь ввел exit
        False - если нет вопросов и не введено команды
    """
    pending = agent.user_interaction.get_pending_question()
    
    # === Если есть ожидающий вопрос от агента ===
    if pending:
        print(f"\n{'!'*60}")
        print(f"  ❓ ВОПРОС ОТ АГЕНТА (#{pending['id']}):")
        print(f"     {pending['question']}")
        if pending.get('context'):
            ctx = pending['context']
            print(f"     Контекст: {ctx[:60]}..." if len(ctx) > 60 else f"     Контекст: {ctx}")
        
        # Показываем suggested answers
        suggestions = agent.user_interaction.generate_suggested_answers(pending['question'])
        print(f"\n  💡 Варианты ответа:")
        for i, sug in enumerate(suggestions, 1):
            short_sug = sug[:50] + "..." if len(sug) > 50 else sug
            print(f"     {i}. {short_sug}")
        print(f"     4. Свой ответ")
        print(f"     p = Пропустить и продолжить работу")
        
        try:
            user_input = input(f"\n  >>> ").strip()
            
            if not user_input:
                return False
            
            # Ответ на вопрос агента
            if user_input.lower() in ['p', 'пропустить', 'skip', 'continue']:
                return False
            
            if user_input.isdigit() and 1 <= int(user_input) <= len(suggestions):
                idx = int(user_input) - 1
                answer = suggestions[idx]
            else:
                answer = user_input
            
            if answer:
                agent_answer_result = agent.user_interaction.submit_answer(pending['id'], answer)
                if agent_answer_result.get('status') == 'answered':
                    result = agent._process_user_answer(answer)
                    print(f"  ✅ {result}")
                    return True
        
        except EOFError:
            return False
        return False
    
    # === Нет вопросов от агента - показываем команды ТОЛЬКО periodically ===
    if cycle_count % 50 == 1 or (cycle_count <= 3):
        print(f"\n{'='*60}")
        print(f"  💬 [{agent.name}] Введите сообщение или команду:")
        print(f"    help/h - справка | status/s - статус | goals/g - цели")
        print(f"    concepts/c - концепции | ask/a <вопрос> - спросить агента")
        print(f"    clear/cl - очистить | exit/q - выйти")
        
        try:
            user_input = input(f"\n  >>> ").strip()
            
            if not user_input:
                return False
            
            handler = UserPromptHandler()
            result = handler.process_command(user_input, agent)
            
            if result == "__EXIT__":
                return "__EXIT__"
            
            # Если пользователь спросил что-то - ставим в очередь открытых вопросов
            if user_input.lower().startswith(('ask ', 'a ')):
                question = user_input[4:].strip()
                if question:
                    result = agent.ask_user(question)
                    queue_size = result.get("queue_size", 0)
                    status = result.get("status", "?")
                    print(f"\n  📤 Вопрос поставлен в очередь мышления (status={status}).")
                    print(f"     Текст: '{question[:60]}...'")
                    if status == "queued":
                        print(f"     Агент будет думать над ним в следующих {result.get('queue_size', 1)*5} циклах.")
                    print(f"     Всего открытых вопросов: {queue_size}")

            return False
        
        except EOFError:
            return False
    
    return False


def run_long_living_agent():
    """Запускает агента в режиме бесконечной жизни."""
    agent = DigitalBeing("Alpha")

    # Загружаем checkpoint если есть
    latest_checkpoint = get_latest_checkpoint("Alpha")
    if latest_checkpoint:
        agent.load_state(latest_checkpoint)
        print(f"\n[{agent.name}] 📂 Состояние восстановлено из {os.path.basename(latest_checkpoint)}")
    else:
        print(f"\n[{agent.name}] 🌅 НОВАЯ ЖИЗНЬ! Агент инициализирован.")

    # Статистика жизни
    start_time = datetime.now()
    cycle_count = agent.cycle_count  # Начинаем с того места где остановились

    # Печатаем начальный статус
    print_status_banner(agent, cycle_count)

    # === ЗАПУСК ДИАЛОГА ОБ ИМЕНИ ===
    # Если у агента ещё не было naming-диалога (фаза NONE) — поздороваемся
    # и попросим пользователя дать ему имя. Это происходит один раз
    # (при новой жизни). После checkpoint — phase восстанавливается и
    # приветствие не повторяется.
    if agent.naming_dialogue.phase == NamingDialogue.PHASE_NONE:
        init_result = agent.start_naming_dialogue(cycle=cycle_count)
        status = init_result.get("status")
        if status == "initiated":
            # Печатаем приветствие агента из последнего сообщения.
            pending_msgs = agent.user_interaction.get_pending_messages(
                include_acknowledged=False
            )
            naming_msg = None
            for m in pending_msgs:
                if m.get("msg_type") == "naming":
                    naming_msg = m
                    break
            if naming_msg is None and pending_msgs:
                naming_msg = pending_msgs[-1]

            print(f"\n{'='*60}")
            print(f"  🤖 Приветствие от [{agent.name}]:")
            print(f"{'='*60}")
            if naming_msg is not None:
                for line in str(naming_msg.get("content", "")).splitlines():
                    print(f"  {line}")
            else:
                print(f"  {agent.name} хочет познакомиться и узнать своё имя.")
            print(f"{'='*60}")

            # Сразу предлагаем пользователю ввести имя.
            try:
                raw = input("\n  >>> Введите имя для агента (или Enter, чтобы оставить '"
                            f"{agent.name}'): ").strip()
            except EOFError:
                raw = ""

            if raw:
                agent.propose_name(raw, cycle=cycle_count)
                accept_msgs = agent.user_interaction.get_pending_messages(
                    include_acknowledged=True
                )
                # Берём самое свежее сообщение naming/proposal/greeting.
                last_msg = accept_msgs[-1] if accept_msgs else None
                if last_msg is not None:
                    print(f"\n  🤖 [{agent.name}]:")
                    for line in str(last_msg.get("content", "")).splitlines():
                        print(f"  {line}")
                # Если пользователь предложил альтернативу — phase CONSIDERING,
                # но для простого CLI-старта этого достаточно.
                print()
            else:
                print(f"  ⏭️ Оставляем временное имя '{agent.name}'.\n")
        elif status == "no_op":
            # Защита от повторного вызова (не должно случаться при phase == NONE,
            # но оставлено для надёжности).
            pass
    elif agent.naming_dialogue.phase == NamingDialogue.PHASE_AWAITING_NAME:
        # Контекст: чекпоинт восстановлен, но диалог был начат и не завершён.
        # Продолжаем с того же места — просто напоминаем пользователю.
        print(f"\n  💭 [{agent.name}] ждёт, пока вы дадите ему имя. "
              f"(Введите имя в строке `>>> name <имя>`)\n")
    
    # Для отслеживания энергии
    low_energy_warned = False
    critical_energy_handled = False
    
    try:
        while agent.is_alive():
            cycle_count += 1
            
            # === ОБРАБОТКА ОТВЕТА ПОЛЬЗОВАТЕЛЯ ===
            user_answered = prompt_user_for_answer(agent, cycle_count)
            
            if user_answered == "__EXIT__":
                print(f"\n\n{'='*60}")
                print(f"  😴 АГЕНТ {agent.name} ЗАСЫПАЕТ (по команде пользователя)")
                print(f"  📅 Прожил: {(datetime.now() - start_time)}")
                print(f"  🔄 Циклов: {cycle_count}")
                print(f"{'='*60}")
                agent.save_state()
                agent.save_mental_models()
                flush_logs()
                print(f"\n[{agent.name}] 💤 Состояние сохранено. Живите спокойно.")
                return
            
            # === ВОССТАНОВЛЕНИЕ ЭНЕРГИИ ===
            if not LR_CONFIG.INFINITE_ENERGY:
                if agent.energy < LR_CONFIG.ENERGY_CRITICAL_THRESHOLD and not critical_energy_handled:
                    get_logger().flush_immediate(f"⚠️ КРИТИЧЕСКАЯ ЭНЕРГИЯ: {agent.energy:.0f}. Ждем восстановления...")
                    print(f"\n  ⚠️ АГЕНТ УСТАЛ (энергия: {agent.energy:.0f})... Отдыхает...")
                    time.sleep(2)
                    agent.energy = min(100, agent.energy + 30)
                    critical_energy_handled = False
                    continue
                
                if agent.energy < LR_CONFIG.ENERGY_LOW_THRESHOLD and not low_energy_warned:
                    print(f"\n  ⚠️ Энергия падает: {agent.energy:.0f}")
                    low_energy_warned = True
            
            if LR_CONFIG.INFINITE_ENERGY and agent.energy < LR_CONFIG.ENERGY_MAX:
                # Этап 2.4: согласовано с tray — потолок ENERGY_MAX (200), не 100.
                agent.energy = min(LR_CONFIG.ENERGY_MAX, agent.energy + 2)
            
            # === ГЕНЕРАЦИЯ СТИМУЛА С ПРИОРИТЕТИЗАЦИЕЙ ===
            stimulus = _generate_prioritized_stimulus(agent)
            
            # === ОСНОВНОЙ ЦИКЛ ЖИЗНИ АГЕНТА ===
            perceived = agent.perceive(stimulus)
            thought = agent.think(perceived)
            action = agent.act(thought)
            agent.evolve()

            # === Запись размышления над открытым вопросом ===
            # Если текущий стимул — это exploration открытого вопроса,
            # фиксируем результат мышления. Это позволяет агенту
            # «думать постепенно» над одним вопросом несколько циклов.
            if getattr(agent, "_open_questions", None) and stimulus.startswith("вопрос: "):
                agent._record_open_question_exploration(stimulus, thought)

            # Вывод мысли только если она интересная (не шаблонная)
            if 'Ментальная модель' in str(thought) or 'Знаю ответ' not in str(thought):
                print(f"  💭 [{cycle_count}] {str(thought)[:80]}")
            # Если агент нашёл ответ на открытый вопрос — показываем
            elif (getattr(agent, "_open_questions", None)
                  and any(q.get("answered") and q.get("answer")
                          and "только что" not in str(thought)
                          for q in agent._open_questions)):
                # Показываем ответы на недавно решённые вопросы
                recently_answered = [
                    q for q in agent._open_questions
                    if q.get("answered") and q.get("answer")
                    and q["last_explored_at"] == cycle_count
                ]
                for q in recently_answered[:2]:
                    print(f"  ✅ Найден ответ на '{q['text'][:50]}...':")
                    print(f"     {q['answer'][:120]}")
            
            # === Периодическое сохранение ментальных моделей ===
            if cycle_count % LR_CONFIG.SAVE_MENTAL_MODELS_INTERVAL == 0:
                agent.save_mental_models()
                get_logger().flush_immediate(f"💾 Ментальные модели сохранены (цикл {cycle_count})")
            
            # === Периодический статус на экран ===
            if cycle_count % LR_CONFIG.STATUS_PRINT_INTERVAL == 0:
                elapsed = (datetime.now() - start_time).total_seconds()
                mins = int(elapsed // 60)
                secs = int(elapsed % 60)
                print_status_banner(agent, cycle_count)
            
            # === Периодическая рефлексия ===
            if cycle_count % SIM_CONFIG.REFLECTION_INTERVAL == 0:
                reflection = agent.reflect()
                if reflection.get('patterns'):
                    for pattern in reflection['patterns'][:2]:
                        print(f"  🔍 Паттерн: {pattern['description'][:50]}... (увер: {pattern['confidence']:.0%})")
            
            # === Умные чекпоинты (внутри save_state) ===
            agent.save_state()

            # === Естественная регенерация энергии (отдых между циклами) ===
            if agent.energy < LR_CONFIG.ENERGY_MAX:
                agent.energy = min(LR_CONFIG.ENERGY_MAX, agent.energy + LR_CONFIG.ENERGY_REGEN_PER_CYCLE)

            # Периодически показываем прогресс
            if cycle_count % 50 == 0:
                get_logger().flush_immediate(f"=== ЖИВУ {cycle_count} ЦИКЛОВ ({agent.intelligence} интеллект) ===")
        
        # Агент умер (энергия кончилась или max_cycles)
        print(f"\n\n{'='*60}")
        print(f"  💀 АГЕНТ {agent.name} ПРЕКРАТИЛ СУЩЕСТВОВАНИЕ")
        print(f"  📅 Прожил: {(datetime.now() - start_time)}")
        print(f"  🔄 Циклов: {cycle_count}")
        print(f"  🧠 Интеллект: {agent.intelligence}")
        print(f"  📚 Концепций: {len(agent.mental_models.concepts)}")
        print(f"{'='*60}")
        
        agent.save_state()
        flush_logs()
        
    except KeyboardInterrupt:
        # Graceful shutdown при Ctrl+C
        print(f"\n\n{'='*60}")
        print(f"  😴 АГЕНТ {agent.name} ЗАСЫПАЕТ (по команде пользователя)")
        print(f"  📅 Прожил: {(datetime.now() - start_time)}")
        print(f"  🔄 Циклов: {cycle_count}")
        print(f"  🧠 Интеллект: {agent.intelligence}")
        print(f"{'='*60}")
        
        # Сохраняем ВСЁ перед остановкой
        agent.save_state()
        agent.save_mental_models()
        flush_logs()
        
        print(f"\n[{agent.name}] 💤 Состояние сохранено. Живите спокойно.")


def _generate_prioritized_stimulus(agent) -> str:
    """Делегирует в ``src.core.stimulus_selector`` (вынесено в Этапе 4.5).

    Сохранено для обратной совместимости с потенциальными внешними импортами.
    Использует ``DEFAULT_GOAL_PRIORITY_PROB = 0.4`` (мягкая приоритезация для CLI).
    """
    from src.core.stimulus_selector import select_stimulus
    return select_stimulus(agent, goal_priority_prob=0.4)


if __name__ == "__main__":
    run_long_living_agent()