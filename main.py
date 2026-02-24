import logging
import os
import json
import random
import datetime
import platform
import psutil
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    CallbackQueryHandler, ConversationHandler, 
    filters, ContextTypes
)
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Токен бота из переменных окружения
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_IDS = [int(id) for id in os.getenv('ADMIN_IDS', '').split(',') if id]
OWNER_ID = int(os.getenv('OWNER_ID', 0))

# Состояния для ConversationHandler
CHOOSING_CLASS, IN_BATTLE, WITHDRAW_AMOUNT = range(3)

# Настройки игры
START_BALANCE = 100
START_HP = 100
START_ATTACK = 10
START_DEFENSE = 5
START_LEVEL = 1
START_EXP = 0

# Настройки пула наград
DEFAULT_TOTAL_POOL = 1_000_000
DEFAULT_DAILY_POOL = 10_000

# Монстры с диапазонами наград
MONSTERS = {
    1: {
        'name': '🐗 Кабан', 
        'level': 1, 
        'hp': 50, 
        'attack': 8, 
        'defense': 2, 
        'exp': 20, 
        'coins_range': (10, 25),
        'drop': 'Шкура кабана',
        'drop_chance': 0.3
    },
    2: {
        'name': '🐺 Волк', 
        'level': 3, 
        'hp': 80, 
        'attack': 12, 
        'defense': 3, 
        'exp': 35, 
        'coins_range': (20, 45),
        'drop': 'Клык волка',
        'drop_chance': 0.35
    },
    3: {
        'name': '🐻 Медведь', 
        'level': 5, 
        'hp': 150, 
        'attack': 18, 
        'defense': 5, 
        'exp': 60, 
        'coins_range': (40, 80),
        'drop': 'Медвежья шкура',
        'drop_chance': 0.4
    },
    4: {
        'name': '👹 Огр', 
        'level': 8, 
        'hp': 250, 
        'attack': 25, 
        'defense': 8, 
        'exp': 100, 
        'coins_range': (80, 150),
        'drop': 'Дубина огра',
        'drop_chance': 0.45
    },
    5: {
        'name': '🐉 Дракон', 
        'level': 12, 
        'hp': 500, 
        'attack': 40, 
        'defense': 15, 
        'exp': 300, 
        'coins_range': (200, 500),
        'drop': 'Чешуя дракона',
        'drop_chance': 0.5
    },
}

# Классы персонажей
CLASSES = {
    'воин': {'hp_bonus': 20, 'attack_bonus': 5, 'defense_bonus': 10},
    'лучник': {'hp_bonus': 10, 'attack_bonus': 10, 'defense_bonus': 5},
    'маг': {'hp_bonus': 5, 'attack_bonus': 15, 'defense_bonus': 5}
}

# ============== ВРЕМЕННАЯ БАЗА ДАННЫХ В ПАМЯТИ (для теста) ==============
# ВНИМАНИЕ: Это временное решение! На Koyeb нужно будет подключить PostgreSQL
users_db = {}
reward_pool = {
    'total_pool': DEFAULT_TOTAL_POOL,
    'distributed_today': 0,
    'max_daily_pool': DEFAULT_DAILY_POOL,
    'last_reset': datetime.datetime.now().date(),
    'enabled': True
}

class TempUser:
    def __init__(self, user_id, username, first_name):
        self.user_id = user_id
        self.username = username
        self.first_name = first_name
        self.level = 1
        self.exp = 0
        self.class_name = 'воин'
        self.hp = 100
        self.max_hp = 100
        self.attack = 10
        self.defense = 5
        self.balance = 100
        self.kills = 0
        self.deaths = 0
        self.rating = 0
        self.in_battle = False
        self.battle_with = None
        self.battle_hp = None
        self.inventory = {}
        self.last_daily = None
        self.daily_streak = 0
        self.created_at = datetime.datetime.now()
        self.last_active = datetime.datetime.now()

# ============== КЛАВИАТУРЫ ==============

def get_main_keyboard():
    """Основная клавиатура"""
    keyboard = [
        [KeyboardButton("👤 Профиль"), KeyboardButton("⚔️ Битва")],
        [KeyboardButton("💰 Баланс"), KeyboardButton("🏆 Рейтинг")],
        [KeyboardButton("🎒 Инвентарь"), KeyboardButton("📅 Ежедневно")],
        [KeyboardButton("❓ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_battle_keyboard():
    """Клавиатура для битвы"""
    keyboard = [
        [InlineKeyboardButton("⚔️ Атаковать", callback_data="battle_attack")],
        [InlineKeyboardButton("🛡 Защищаться", callback_data="battle_defend")],
        [InlineKeyboardButton("🏃 Сбежать", callback_data="battle_flee")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_monster_selection_keyboard():
    """Клавиатура выбора монстра"""
    keyboard = [
        [InlineKeyboardButton("🐗 Кабан (Ур.1) 10-25💰", callback_data="monster_1")],
        [InlineKeyboardButton("🐺 Волк (Ур.3) 20-45💰", callback_data="monster_2")],
        [InlineKeyboardButton("🐻 Медведь (Ур.5) 40-80💰", callback_data="monster_3")],
        [InlineKeyboardButton("👹 Огр (Ур.8) 80-150💰", callback_data="monster_4")],
        [InlineKeyboardButton("🐉 Дракон (Ур.12) 200-500💰", callback_data="monster_5")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_class_selection_keyboard():
    """Клавиатура выбора класса"""
    keyboard = [
        [InlineKeyboardButton("⚔️ Воин", callback_data="class_воин")],
        [InlineKeyboardButton("🏹 Лучник", callback_data="class_лучник")],
        [InlineKeyboardButton("🔮 Маг", callback_data="class_маг")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ============== ИГРОВАЯ ЛОГИКА ==============

class GameLogic:
    @staticmethod
    def calculate_level(exp):
        level = 1
        exp_needed = 100
        total_exp = 0
        
        while exp >= total_exp + exp_needed:
            total_exp += exp_needed
            level += 1
            exp_needed = int(exp_needed * 1.5)
        
        return level, exp_needed, exp - total_exp

    @staticmethod
    def calculate_battle(player, monster):
        player_attack = player.attack + random.randint(-3, 5)
        monster_attack = monster['attack'] + random.randint(-2, 3)
        
        crit = random.random() < 0.1
        if crit:
            player_attack *= 2
        
        player_damage = max(1, player_attack - monster['defense'] // 2)
        monster_damage = max(1, monster_attack - player.defense // 2)
        
        return {
            'player_damage': player_damage,
            'monster_damage': monster_damage,
            'crit': crit,
            'player_hp_left': player.battle_hp - monster_damage,
            'monster_hp_left': monster['hp'] - player_damage
        }

    @staticmethod
    def calculate_reward(monster, player_level):
        min_coins, max_coins = monster['coins_range']
        base_coins = random.randint(min_coins, max_coins)
        base_exp = monster['exp']
        
        level_diff = player_level - monster['level']
        if level_diff > 0:
            level_modifier = max(0.5, 1.0 - level_diff * 0.1)
        else:
            level_modifier = min(1.5, 1.0 + abs(level_diff) * 0.15)
        
        random_modifier = random.uniform(0.9, 1.1)
        final_modifier = level_modifier * random_modifier
        
        coins_gained = int(base_coins * final_modifier)
        exp_gained = int(base_exp * final_modifier)
        
        drop_chance = random.random()
        extra_drop = None
        if drop_chance < monster['drop_chance']:
            extra_drop = monster['drop']
        
        return {
            'exp': exp_gained,
            'coins': coins_gained,
            'drop': extra_drop,
            'modifier': final_modifier
        }

# ============== СИСТЕМА ПУЛА ==============

class RewardSystem:
    @staticmethod
    def get_pool_status():
        global reward_pool
        
        # Проверяем сброс дня
        today = datetime.datetime.now().date()
        if reward_pool['last_reset'] != today:
            reward_pool['distributed_today'] = 0
            reward_pool['last_reset'] = today
        
        return {
            'total_pool': reward_pool['total_pool'],
            'distributed_today': reward_pool['distributed_today'],
            'max_daily_pool': reward_pool['max_daily_pool'],
            'remaining_today': reward_pool['max_daily_pool'] - reward_pool['distributed_today'],
            'remaining_total': reward_pool['total_pool'],
            'enabled': reward_pool['enabled'],
            'percent_used': (reward_pool['distributed_today'] / reward_pool['max_daily_pool'] * 100) if reward_pool['max_daily_pool'] > 0 else 0
        }

    @staticmethod
    def can_earn(amount):
        global reward_pool
        
        if not reward_pool['enabled']:
            return False, "🚫 Система наград временно отключена"
        
        if reward_pool['distributed_today'] + amount > reward_pool['max_daily_pool']:
            remaining = reward_pool['max_daily_pool'] - reward_pool['distributed_today']
            return False, f"⚠️ Дневной лимит: осталось {remaining} монет"
        
        if amount > reward_pool['total_pool']:
            return False, f"⚠️ В пуле осталось {reward_pool['total_pool']} монет"
        
        return True, "✅ Можно заработать"

    @staticmethod
    def add_earnings(amount):
        global reward_pool
        can_earn, message = RewardSystem.can_earn(amount)
        
        if not can_earn:
            return False, message
        
        reward_pool['total_pool'] -= amount
        reward_pool['distributed_today'] += amount
        
        return True, f"✨ +{amount} монет!"

# ============== ОБРАБОТЧИКИ КОМАНД ==============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if user.id not in users_db:
        users_db[user.id] = TempUser(user.id, user.username, user.first_name)
        
        welcome_text = f"""
🌟 ДОБРО ПОЖАЛОВАТЬ В RUCOY BATTLE! 🌟

Привет, {user.first_name}!

⚔️ ЧТО ТЕБЯ ЖДЕТ:
• Сражения с монстрами
• Прокачка персонажа
• Заработок валюты
• Рейтинг лучших игроков

🏁 ВЫБЕРИ КЛАСС:
        """
        await update.message.reply_text(
            welcome_text,
            reply_markup=get_class_selection_keyboard()
        )
        return CHOOSING_CLASS
    else:
        await update.message.reply_text(
            f"С возвращением, {user.first_name}! 👋",
            reply_markup=get_main_keyboard()
        )
    
    return ConversationHandler.END

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if user.id not in users_db:
        await update.message.reply_text("Сначала введи /start!")
        return
    
    db_user = users_db[user.id]
    level, exp_needed, current_exp = GameLogic.calculate_level(db_user.exp)
    
    profile_text = f"""
👤 ПРОФИЛЬ ИГРОКА

📛 Имя: {db_user.first_name}
⚔️ Класс: {db_user.class_name}
🏆 Уровень: {db_user.level}
✨ Опыт: {current_exp}/{exp_needed}

❤️ HP: {db_user.hp}/{db_user.max_hp}
⚔️ Атака: {db_user.attack}
🛡 Защита: {db_user.defense}

👾 Убито: {db_user.kills}
💀 Смертей: {db_user.deaths}
💰 Баланс: {db_user.balance} монет
💎 Рейтинг: {db_user.rating}
    """
    
    await update.message.reply_text(profile_text, reply_markup=get_main_keyboard())

async def battle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if user.id not in users_db:
        await update.message.reply_text("Сначала введи /start!")
        return
    
    db_user = users_db[user.id]
    
    if db_user.hp <= 0:
        await update.message.reply_text("💀 Ты мертв! Воскресни за 50 монет командой /revive")
        return
    
    if db_user.in_battle:
        await update.message.reply_text("Ты уже в битве!")
        return
    
    await update.message.reply_text(
        "👾 ВЫБЕРИ ПРОТИВНИКА:",
        reply_markup=get_monster_selection_keyboard()
    )

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if user.id not in users_db:
        await update.message.reply_text("Сначала введи /start!")
        return
    
    db_user = users_db[user.id]
    pool_status = RewardSystem.get_pool_status()
    
    balance_text = f"""
💰 ТВОЙ БАЛАНС

Доступно: {db_user.balance} монет

📊 ПУЛ НАГРАД:
• Осталось сегодня: {pool_status['remaining_today']} монет
• Всего в пуле: {pool_status['total_pool']} монет
• Выдано сегодня: {pool_status['distributed_today']} монет
    """
    
    await update.message.reply_text(balance_text)

async def rating_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if user.id not in users_db:
        await update.message.reply_text("Сначала введи /start!")
        return
    
    # Сортируем игроков по рейтингу
    sorted_users = sorted(users_db.values(), key=lambda x: x.rating, reverse=True)
    
    top_text = "🏆 ТОП 5 ИГРОКОВ\n\n"
    
    for i, u in enumerate(sorted_users[:5], 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        top_text += f"{medal} {u.first_name} | Ур.{u.level} | {u.rating}⭐ | {u.balance}💰\n"
    
    # Находим место текущего игрока
    user_rank = next((i for i, u in enumerate(sorted_users, 1) if u.user_id == user.id), len(sorted_users) + 1)
    top_text += f"\n📊 Твое место: #{user_rank}"
    
    await update.message.reply_text(top_text)

async def inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if user.id not in users_db:
        await update.message.reply_text("Сначала введи /start!")
        return
    
    db_user = users_db[user.id]
    
    inv_text = "🎒 ИНВЕНТАРЬ\n\n"
    
    if not db_user.inventory:
        inv_text += "Пусто 🥲\n\nСражайся с монстрами, чтобы получить дроп!"
    else:
        for item, count in db_user.inventory.items():
            inv_text += f"• {item} x{count}\n"
    
    await update.message.reply_text(inv_text)

async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if user.id not in users_db:
        await update.message.reply_text("Сначала введи /start!")
        return
    
    db_user = users_db[user.id]
    today = datetime.datetime.now().date()
    
    if db_user.last_daily and db_user.last_daily.date() == today:
        await update.message.reply_text("Ты уже получил бонус сегодня!")
        return
    
    # Расчет бонуса
    if db_user.last_daily and (today - db_user.last_daily.date()).days == 1:
        db_user.daily_streak += 1
    else:
        db_user.daily_streak = 1
    
    base_coins = 50
    base_exp = 30
    streak_bonus = min(db_user.daily_streak * 0.1, 1.0)
    random_mult = random.uniform(0.8, 1.2)
    
    coins_bonus = int(base_coins * (1 + streak_bonus) * random_mult)
    exp_bonus = int(base_exp * (1 + streak_bonus) * random_mult)
    
    # Проверяем пул
    can_earn, message = RewardSystem.can_earn(coins_bonus)
    
    if can_earn:
        success, _ = RewardSystem.add_earnings(coins_bonus)
        if success:
            db_user.balance += coins_bonus
            db_user.exp += exp_bonus
            db_user.last_daily = datetime.datetime.now()
            
            daily_text = f"""
📅 ЕЖЕДНЕВНЫЙ БОНУС

День {db_user.daily_streak} подряд!

💰 Монеты: +{coins_bonus}
✨ Опыт: +{exp_bonus}

🔥 Стрик: {db_user.daily_streak} дней
            """
        else:
            daily_text = "⚠️ Пул наград пуст!"
    else:
        daily_text = f"⚠️ {message}"
    
    await update.message.reply_text(daily_text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
📚 КОМАНДЫ:

👤 Профиль - статистика
⚔️ Битва - сражения
💰 Баланс - монеты
🏆 Рейтинг - топ игроков
🎒 Инвентарь - предметы
📅 Ежедневно - бонус
❓ Помощь - это меню
    """
    
    await update.message.reply_text(help_text)

async def revive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if user.id not in users_db:
        await update.message.reply_text("Сначала введи /start!")
        return
    
    db_user = users_db[user.id]
    
    if db_user.hp > 0:
        await update.message.reply_text("Ты еще жив!")
        return
    
    if db_user.balance < 50:
        await update.message.reply_text("❌ Недостаточно монет! Нужно 50.")
        return
    
    db_user.balance -= 50
    db_user.hp = db_user.max_hp // 2
    
    await update.message.reply_text(f"✨ Ты воскрес! HP: {db_user.hp}")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка статуса бота"""
    user = update.effective_user
    
    # Только для владельца
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ Доступ запрещен")
        return
    
    pool_status = RewardSystem.get_pool_status()
    
    status_text = f"""
📊 СТАТУС БОТА

🖥️ Хостинг: Koyeb
🐍 Python: {platform.python_version()}
👥 Пользователей: {len(users_db)}

💰 ПУЛ НАГРАД:
• Всего: {pool_status['total_pool']:,} монет
• Сегодня: {pool_status['distributed_today']:,}/{pool_status['max_daily_pool']:,}
• Осталось: {pool_status['remaining_today']:,} монет
• Использовано: {pool_status['percent_used']:.1f}%
• Статус: {'✅ Вкл' if pool_status['enabled'] else '❌ Выкл'}
    """
    
    await update.message.reply_text(status_text)

# ============== ОБРАБОТЧИК КНОПОК ==============

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    
    if user.id not in users_db:
        users_db[user.id] = TempUser(user.id, user.username, user.first_name)
    
    db_user = users_db[user.id]
    
    # Выбор класса
    if query.data.startswith('class_'):
        class_name = query.data.replace('class_', '')
        db_user.class_name = class_name
        
        if class_name == 'воин':
            db_user.max_hp += 20
            db_user.hp = db_user.max_hp
            db_user.attack += 5
            db_user.defense += 10
        elif class_name == 'лучник':
            db_user.max_hp += 10
            db_user.hp = db_user.max_hp
            db_user.attack += 10
            db_user.defense += 5
        elif class_name == 'маг':
            db_user.max_hp += 5
            db_user.hp = db_user.max_hp
            db_user.attack += 15
            db_user.defense += 5
        
        await query.edit_message_text(
            f"✅ Ты выбрал класс {class_name.upper()}!\n\n"
            f"❤️ HP: {db_user.hp}\n"
            f"⚔️ Атака: {db_user.attack}\n"
            f"🛡 Защита: {db_user.defense}\n\n"
            f"Теперь можешь начинать! /battle",
            reply_markup=get_main_keyboard()
        )
    
    # Выбор монстра
    elif query.data.startswith('monster_'):
        monster_id = int(query.data.replace('monster_', ''))
        monster = MONSTERS[monster_id]
        
        if db_user.level < monster['level'] - 2:
            await query.edit_message_text(
                f"⚠️ Этот монстр слишком силен!\n"
                f"Твой уровень: {db_user.level}, нужно минимум {monster['level']-2}"
            )
            return
        
        db_user.in_battle = True
        db_user.battle_with = monster_id
        db_user.battle_hp = monster['hp']
        
        battle_text = f"""
⚔️ БИТВА С {monster['name']}!

❤️ HP врага: {monster['hp']}
💰 Награда: {monster['coins_range'][0]}-{monster['coins_range'][1]} монет

❤️ Твое HP: {db_user.hp}/{db_user.max_hp}
⚔️ Атака: {db_user.attack}
🛡 Защита: {db_user.defense}

🎮 Твой ход!
        """
        
        await query.edit_message_text(battle_text, reply_markup=get_battle_keyboard())
    
    # Действия в битве
    elif query.data == 'battle_attack':
        if not db_user.in_battle:
            await query.edit_message_text("❌ Битва не найдена!")
            return
        
        monster_id = db_user.battle_with
        monster = MONSTERS[monster_id]
        
        result = GameLogic.calculate_battle(db_user, monster)
        
        db_user.battle_hp = result['monster_hp_left']
        db_user.hp = result['player_hp_left']
        
        # Проверка смерти игрока
        if db_user.hp <= 0:
            db_user.deaths += 1
            db_user.in_battle = False
            db_user.hp = 0
            
            await query.edit_message_text(
                f"💀 Ты погиб! Воскресни за 50 монет.",
                reply_markup=get_main_keyboard()
            )
            return
        
        # Проверка победы
        if result['monster_hp_left'] <= 0:
            reward = GameLogic.calculate_reward(monster, db_user.level)
            
            # Проверяем пул
            can_earn, message = RewardSystem.can_earn(reward['coins'])
            
            if can_earn:
                success, _ = RewardSystem.add_earnings(reward['coins'])
                
                if success:
                    db_user.balance += reward['coins']
                    db_user.exp += reward['exp']
                    db_user.kills += 1
                    db_user.rating += 10
                    
                    if reward['drop']:
                        db_user.inventory[reward['drop']] = db_user.inventory.get(reward['drop'], 0) + 1
                    
                    # Проверка уровня
                    new_level, _, _ = GameLogic.calculate_level(db_user.exp)
                    if new_level > db_user.level:
                        old_level = db_user.level
                        while db_user.level < new_level:
                            db_user.level += 1
                            db_user.max_hp += 20
                            db_user.hp = db_user.max_hp
                            db_user.attack += 3
                            db_user.defense += 2
                        
                        level_text = f"\n\n✨ НОВЫЙ УРОВЕНЬ! {db_user.level}!"
                    else:
                        level_text = ""
                    
                    victory_text = f"""
🏆 ПОБЕДА!

💰 Монеты: +{reward['coins']}
✨ Опыт: +{reward['exp']}
📊 Модификатор: {reward['modifier']:.1f}x
{('📦 Дроп: ' + reward['drop']) if reward['drop'] else ''}{level_text}
                    """
                else:
                    victory_text = "⚠️ Ошибка начисления награды"
            else:
                victory_text = f"⚠️ {message}\nНаграда не начислена."
            
            db_user.in_battle = False
            await query.edit_message_text(victory_text, reply_markup=get_main_keyboard())
            return
        
        # Продолжение боя
        result_text = f"""
⚔️ ТВОЯ АТАКА!

Ты нанес {result['player_damage']} урона!
HP врага: {result['monster_hp_left']}/{monster['hp']}

{'✅ КРИТ!' if result['crit'] else ''}
Получено урона: {result['monster_damage']}
Твое HP: {db_user.hp}/{db_user.max_hp}
        """
        
        await query.edit_message_text(result_text, reply_markup=get_battle_keyboard())
    
    elif query.data == 'battle_defend':
        heal = int(db_user.max_hp * 0.1)
        db_user.hp = min(db_user.max_hp, db_user.hp + heal)
        await query.edit_message_text(
            f"🛡 Защита! Восстановлено +{heal} HP\n"
            f"Текущее HP: {db_user.hp}/{db_user.max_hp}",
            reply_markup=get_battle_keyboard()
        )
    
    elif query.data == 'battle_flee':
        db_user.in_battle = False
        await query.edit_message_text(
            "🏃 Ты сбежал!",
            reply_markup=get_main_keyboard()
        )

# ============== ОБРАБОТЧИК СООБЩЕНИЙ ==============

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text == "👤 Профиль":
        await profile(update, context)
    elif text == "⚔️ Битва":
        await battle(update, context)
    elif text == "💰 Баланс":
        await balance(update, context)
    elif text == "🏆 Рейтинг":
        await rating_command(update, context)
    elif text == "🎒 Инвентарь":
        await inventory(update, context)
    elif text == "📅 Ежедневно":
        await daily(update, context)
    elif text == "❓ Помощь":
        await help_command(update, context)
    else:
        await update.message.reply_text("Используй кнопки меню")

# ============== FLASK APP ДЛЯ HEALTH CHECK ==============

app = Flask(__name__)

@app.route('/')
def index():
    return '🤖 Rucoy Bot is running!'

@app.route('/health')
def health():
    return 'OK', 200

@app.route('/stats')
def stats():
    pool_status = RewardSystem.get_pool_status()
    return {
        'users': len(users_db),
        'pool': pool_status,
        'status': 'active'
    }

# ============== ЗАПУСК БОТА ==============

async def run_bot():
    """Запуск бота"""
    global application
    
    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()
    
    # ConversationHandler для создания персонажа
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            CHOOSING_CLASS: [CallbackQueryHandler(button_callback)],
        },
        fallbacks=[CommandHandler('start', start)]
    )
    
    # Добавляем обработчики
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('profile', profile))
    application.add_handler(CommandHandler('balance', balance))
    application.add_handler(CommandHandler('rating', rating_command))
    application.add_handler(CommandHandler('battle', battle))
    application.add_handler(CommandHandler('inventory', inventory))
    application.add_handler(CommandHandler('daily', daily))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('revive', revive))
    application.add_handler(CommandHandler('status', status))
    
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Запускаем бота
    print(f"🤖 Бот запущен! Владелец ID: {OWNER_ID}")
    print(f"💰 Пул наград: {DEFAULT_TOTAL_POOL:,} монет")
    
    await application.initialize()
    await application.start()
    
    # Используем polling
    await application.updater.start_polling()
    
    # Держим бота запущенным
    while True:
        await asyncio.sleep(1)

def main():
    """Главная функция"""
    import asyncio
    import threading
    
    # Запускаем бота в отдельном потоке
    def start_bot():
        asyncio.run(run_bot())
    
    bot_thread = threading.Thread(target=start_bot, daemon=True)
    bot_thread.start()
    
    # Запускаем Flask для health checks
    port = int(os.environ.get('PORT', 8000))
    print(f"🌐 Flask сервер запущен на порту {port}")
    app.run(host='0.0.0.0', port=port)

if __name__ == '__main__':
    main()