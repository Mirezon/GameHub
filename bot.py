
# ...existing code...

# ...existing code...
import logging
import asyncio
import json
import os
import random
import re
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import time
from pathlib import Path

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
    CallbackQuery,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

import aiohttp
from urllib.parse import urlparse

from config import Config

# Настройка логгера и диспетчера до регистрации обработчиков
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализируем хранилище состояний и диспетчер заранее,
# чтобы декораторы @dp.* могли использовать `dp` при импорте модуля.
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# recent_sent_files: user_id -> file_unique_id (used to suppress duplicates)
# recent_sent_files: user_id -> (file_unique_id, timestamp)
recent_sent_files: Dict[int, tuple] = {}
# recent_sending: user_id -> bool (lock to prevent concurrent duplicate sends)
recent_sending: Dict[int, bool] = {}

# Состояния FSM
class SearchStates(StatesGroup):
    search_by_name = State()
    search_by_genre = State()
    search_by_size = State()

class AdminStates(StatesGroup):
    # Для приложений
    add_app_name = State()
    add_app_genre = State()
    add_app_size = State()
    add_app_description = State()
    add_app_post_link = State()
    add_app_file_link = State()
    
    # Для редактирования приложений
    edit_app_select = State()
    edit_app_field = State()
    edit_app_value = State()
    
    # Для удаления приложений
    delete_app_select = State()
    
    # Для администраторов
    add_admin_id = State()
    add_manager_id = State()
    remove_admin_id = State()
    change_admin_level = State()
    
    # Для каналов
    add_channel_title = State()
    add_channel_link = State()
    add_channel_description = State()
    delete_channel_select = State()
    # Редактирование канала
    edit_channel_select = State()
    edit_channel_field = State()
    edit_channel_value = State()
    
    # Для розыгрышей
    add_giveaway_title = State()
    add_giveaway_description = State()
    add_giveaway_prize = State()
    add_giveaway_end_datetime = State()
    edit_giveaway_select = State()
    edit_giveaway_field = State()
    edit_giveaway_value = State()

class SuggestionStates(StatesGroup):
    wait_for_suggestion = State()
    suggest_game_name = State()
    suggest_game_genre = State()
    suggest_game_link = State()
    wait_for_reject_reason = State()


class ContactManagerStates(StatesGroup):
    waiting_for_message = State()

class IdeaSuggestionStates(StatesGroup):
    wait_for_idea = State()

# Вспомогательные функции
def validate_url(url: str) -> bool:
    """Валидация URL"""
    if not url:
        return True
    pattern = re.compile(
        r'^(https?://)?'  # http:// или https://
        r'(([A-Z0-9][A-Z0-9_-]*)(\.[A-Z0-9][A-Z0-9_-]*)+)'  # домен
        r'(:\d+)?'  # порт
        r'(/.*)?$',  # путь
        re.IGNORECASE
    )
    return bool(pattern.match(url))

def validate_datetime(datetime_str: str) -> bool:
    """Валидация даты и времени в формате DD.MM.YYYY HH:MM"""
    try:
        datetime.strptime(datetime_str, "%d.%m.%Y %H:%M")
        return True
    except ValueError:
        return False

def format_time_remaining(end_datetime_str: str) -> str:
    """Форматирование оставшегося времени до окончания розыгрыша"""
    try:
        end_datetime = datetime.strptime(end_datetime_str, "%d.%m.%Y %H:%M")
        now = datetime.now()
        
        if now >= end_datetime:
            return "⏰ Розыгрыш завершен"
        
        delta = end_datetime - now
        
        days = delta.days
        hours = delta.seconds // 3600
        minutes = (delta.seconds % 3600) // 60
        
        if days > 0:
            return f"⏳ Осталось: {days} дн. {hours} ч."
        elif hours > 0:
            return f"⏳ Осталось: {hours} ч. {minutes} мин."
        else:
            return f"⏳ Осталось: {minutes} мин."
    except:
        return "⏰ Время не указано"

# База данных в памяти
class Database:
    def __init__(self):
        self.channels = Config.load_json_file(Config.CHANNELS_FILE, [])
        self.apps = Config.load_json_file(Config.APPS_FILE, [])
        self.suggestions = Config.load_json_file(Config.SUGGESTIONS_FILE, [])
        self.giveaways = Config.load_json_file(Config.GIVEAWAYS_FILE, [])
        self.users = Config.load_json_file(Config.USERS_FILE, [])
        self.jobs = Config.load_json_file(Config.JOBS_FILE, [])
    
    def save_channels(self):
        Config.save_json_file(Config.CHANNELS_FILE, self.channels)
    
    def save_apps(self):
        Config.save_json_file(Config.APPS_FILE, self.apps)
    
    def save_suggestions(self):
        Config.save_json_file(Config.SUGGESTIONS_FILE, self.suggestions)
    
    def save_giveaways(self):
        Config.save_json_file(Config.GIVEAWAYS_FILE, self.giveaways)
    
    def save_jobs(self):
        Config.save_json_file(Config.JOBS_FILE, self.jobs)

    def save_users(self):
        Config.save_json_file(Config.USERS_FILE, self.users)
    
    def add_app(self, app_data: Dict) -> bool:
        """Добавление приложения"""
        try:
            # Валидация данных
            if not app_data.get('name'):
                return False
            
            app_data['id'] = len(self.apps) + 1
            app_data['added_date'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            self.apps.append(app_data)
            self.save_apps()
            return True
        except Exception as e:
            logger.error(f"Ошибка добавления приложения: {e}")
            return False
    
    def update_app(self, app_id: int, field: str, value: str) -> bool:
        """Обновление приложения"""
        for app in self.apps:
            if app.get('id') == app_id:
                app[field] = value
                app['modified_date'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.save_apps()
                return True
        return False
    
    def delete_app(self, app_id: int) -> bool:
        """Удаление приложения"""
        for i, app in enumerate(self.apps):
            if app.get('id') == app_id:
                self.apps.pop(i)
                self.save_apps()
                return True
        return False
    
    def add_channel(self, channel_data: Dict) -> bool:
        """Добавление канала"""
        self.channels.append(channel_data)
        self.save_channels()
        return True

    def add_user(self, user_id: int, username: str = "", first_name: str = "") -> bool:
        """Добавление/обновление пользователя в реестр пользователей"""
        for u in self.users:
            if u.get('id') == user_id:
                # обновим данные и дату последнего взаимодействия
                u['username'] = username or u.get('username', '')
                u['first_name'] = first_name or u.get('first_name', '')
                u['last_seen'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.save_users()
                return True

        # иначе добавляем нового
        self.users.append({
            'id': user_id,
            'username': username or f'user_{user_id}',
            'first_name': first_name or 'Пользователь',
            'added_date': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'last_seen': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        self.save_users()
        return True
    
    def delete_channel(self, channel_index: int) -> bool:
        """Удаление канала по индексу"""
        if 0 <= channel_index < len(self.channels):
            self.channels.pop(channel_index)
            self.save_channels()
            return True
        return False
    
    def add_suggestion(self, suggestion_data: Dict) -> bool:
        """Добавление предложения"""
        suggestion_data['id'] = len(self.suggestions) + 1
        suggestion_data['date'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        suggestion_data['status'] = 'pending'
        self.suggestions.append(suggestion_data)
        self.save_suggestions()
        return True
    
    def update_suggestion_status(self, suggestion_id: int, status: str) -> bool:
        """Обновление статуса предложения"""
        for suggestion in self.suggestions:
            if suggestion.get('id') == suggestion_id:
                suggestion['status'] = status
                self.save_suggestions()
                return True
        return False

    def set_suggestion_rejection(self, suggestion_id: int, reason: str) -> bool:
        """Отметить предложение как отклонённое и сохранить причину"""
        for suggestion in self.suggestions:
            if suggestion.get('id') == suggestion_id:
                suggestion['status'] = 'rejected'
                suggestion['rejection_reason'] = reason
                suggestion['modified_date'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.save_suggestions()
                return True
        return False

    def get_suggestion_by_id(self, suggestion_id: int) -> Dict:
        """Получение предложения по ID"""
        for suggestion in self.suggestions:
            if suggestion.get('id') == suggestion_id:
                return suggestion
        return {}
    
    def add_giveaway(self, giveaway_data: Dict) -> bool:
        """Добавление розыгрыша"""
        giveaway_data['id'] = len(self.giveaways) + 1
        giveaway_data['created_date'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        giveaway_data['participants'] = []
        giveaway_data['ended'] = False
        self.giveaways.append(giveaway_data)
        self.save_giveaways()
        return True
    
    def update_giveaway(self, giveaway_id: int, field: str, value) -> bool:
        """Обновление розыгрыша"""
        for giveaway in self.giveaways:
            if giveaway.get('id') == giveaway_id:
                giveaway[field] = value
                giveaway['modified_date'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.save_giveaways()
                return True
        return False
    
    def delete_giveaway(self, giveaway_id: int) -> bool:
        """Удаление розыгрыша"""
        for i, giveaway in enumerate(self.giveaways):
            if giveaway.get('id') == giveaway_id:
                self.giveaways.pop(i)
                self.save_giveaways()
                return True
        return False
    
    def get_giveaway_by_id(self, giveaway_id: int) -> Dict:
        """Получение розыгрыша по ID"""
        for giveaway in self.giveaways:
            if giveaway.get('id') == giveaway_id:
                return giveaway
        return {}
    
    def end_giveaway(self, giveaway_id: int, winner_id: int = None, winner_username: str = None) -> bool:
        """Завершение розыгрыша с выбором победителя"""
        for giveaway in self.giveaways:
            if giveaway.get('id') == giveaway_id:
                giveaway['ended'] = True
                giveaway['end_date_actual'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                if winner_id and winner_username:
                    giveaway['winner'] = {
                        'id': winner_id,
                        'username': winner_username
                    }
                
                self.save_giveaways()
                return True
        return False
    
    def add_participant(self, giveaway_id: int, user_id: int, username: str, first_name: str) -> bool:
        """Добавление участника в розыгрыш"""
        for giveaway in self.giveaways:
            if giveaway.get('id') == giveaway_id:
                # Проверяем, не участвует ли уже пользователь
                if any(participant.get('id') == user_id for participant in giveaway.get('participants', [])):
                    return False
                
                giveaway['participants'].append({
                    'id': user_id,
                    'username': username,
                    'first_name': first_name,
                    'joined_date': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                self.save_giveaways()
                return True
        return False
    
    def is_participant(self, giveaway_id: int, user_id: int) -> bool:
        """Проверка, участвует ли пользователь в розыгрыше"""
        for giveaway in self.giveaways:
            if giveaway.get('id') == giveaway_id:
                for participant in giveaway.get('participants', []):
                    if participant.get('id') == user_id:
                        return True
        return False
    
    def search_by_name(self, name: str) -> List[Dict]:
        """Поиск по названию"""
        name_lower = name.lower()
        return [app for app in self.apps if name_lower in app.get('name', '').lower()]
    
    def search_by_genre(self, genre: str) -> List[Dict]:
        """Поиск по жанру"""
        genre_lower = genre.lower()
        return [app for app in self.apps if app.get('genre', '').lower() == genre_lower]
    
    def search_by_size(self, size_category: str) -> List[Dict]:
        """Поиск по размеру"""
        return [app for app in self.apps if app.get('size_category', '') == size_category]
    
    def get_app_by_id(self, app_id: int) -> Dict:
        """Получение приложения по ID"""
        for app in self.apps:
            if app.get('id') == app_id:
                return app
        return {}
    
    def get_random_app(self) -> Dict:
        """Получение случайного приложения"""
        if not self.apps:
            return {}
        return random.choice(self.apps)
    
    def get_apps_paginated(self, page: int = 1, per_page: int = 5) -> Dict:
        """Получение приложений с пагинацией"""
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        apps_slice = self.apps[start_idx:end_idx]
        
        total = len(self.apps)
        total_pages = (total + per_page - 1) // per_page if total > 0 else 1
        
        return {
            'apps': apps_slice,
            'page': page,
            'per_page': per_page,
            'total': total,
            'total_pages': total_pages
        }
    
    def get_giveaways_paginated(self, page: int = 1, per_page: int = 5) -> Dict:
        """Получение розыгрышей с пагинацией"""
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        giveaways_slice = self.giveaways[start_idx:end_idx]
        
        total = len(self.giveaways)
        total_pages = (total + per_page - 1) // per_page if total > 0 else 1
        
        return {
            'giveaways': giveaways_slice,
            'page': page,
            'per_page': per_page,
            'total': total,
            'total_pages': total_pages
        }
    
    def get_active_giveaways(self) -> List[Dict]:
        """Получение активных розыгрышей"""
        active_giveaways = []
        for giveaway in self.giveaways:
            if not giveaway.get('ended', False):
                try:
                    end_datetime = datetime.strptime(giveaway.get('end_datetime', ''), "%d.%m.%Y %H:%M")
                    if datetime.now() < end_datetime:
                        active_giveaways.append(giveaway)
                except:
                    # Если дата некорректная, считаем розыгрыш активным
                    active_giveaways.append(giveaway)
        return active_giveaways
    
    def get_ended_giveaways(self) -> List[Dict]:
        """Получение завершенных розыгрышей"""
        ended_giveaways = []
        for giveaway in self.giveaways:
            if giveaway.get('ended', False):
                ended_giveaways.append(giveaway)
            else:
                try:
                    end_datetime = datetime.strptime(giveaway.get('end_datetime', ''), "%d.%m.%Y %H:%M")
                    if datetime.now() >= end_datetime:
                        giveaway['ended'] = True
                        ended_giveaways.append(giveaway)
                        self.save_giveaways()
                except:
                    pass
        return ended_giveaways
    
    def get_pending_suggestions(self) -> List[Dict]:
        """Получение ожидающих предложений"""
        return [s for s in self.suggestions if s.get('status') == 'pending']
    
    def get_suggestions_paginated(self, page: int = 1, per_page: int = 10) -> Dict:
        """Получение предложений с пагинацией"""
        suggestions = self.get_pending_suggestions()
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        suggestions_slice = suggestions[start_idx:end_idx]
        
        total = len(suggestions)
        total_pages = (total + per_page - 1) // per_page if total > 0 else 1
        
        return {
            'suggestions': suggestions_slice,
            'page': page,
            'per_page': per_page,
            'total': total,
            'total_pages': total_pages
        }
    
    def get_stats(self) -> Dict:
        """Получение статистики"""
        active_giveaways = self.get_active_giveaways()
        ended_giveaways = self.get_ended_giveaways()
        pending_suggestions = len(self.get_pending_suggestions())
        
        return {
            'apps_count': len(self.apps),
            'channels_count': len(self.channels),
            'suggestions_count': len(self.suggestions),
            'pending_suggestions': pending_suggestions,
            'giveaways_count': len(self.giveaways),
            'active_giveaways': len(active_giveaways),
            'ended_giveaways': len(ended_giveaways)
        }

db = Database()

# ================== КЛАВИАТУРЫ ==================

def get_main_menu(user_id: int) -> ReplyKeyboardMarkup:
    """Главное меню"""
    keyboard_buttons = [
        [KeyboardButton(text="🔍 Поиск"), KeyboardButton(text="🎲 Рандомная игра")],
        [KeyboardButton(text="🎁 Розыгрыши"), KeyboardButton(text="📢 Каналы")],
        [KeyboardButton(text="💡 Предложить игру"), KeyboardButton(text="💼 Вакансии")],
        [KeyboardButton(text="🔒 Приватный доступ"), KeyboardButton(text="ℹ️ Помощь")]
    ]
    
    # Добавляем админ-панель ТОЛЬКО если пользователь админ
    if Config.is_admin(user_id):
        keyboard_buttons.append([KeyboardButton(text="⚙️ Админ-панель")])
    
    return ReplyKeyboardMarkup(
        keyboard=keyboard_buttons,
        resize_keyboard=True
    )

def get_search_menu() -> ReplyKeyboardMarkup:
    """Меню поиска"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔍 По названию"), KeyboardButton(text="🎮 По жанру")],
            [KeyboardButton(text="📱 По размеру"), KeyboardButton(text="📋 Все приложения")],
            [KeyboardButton(text="🎲 Рандомная игра"), KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )

def get_admin_menu(user_id: int) -> ReplyKeyboardMarkup:
    """Меню администратора с учетом уровня доступа"""
    keyboard_buttons = []
    
    # Базовые кнопки для всех админов
    if Config.is_editor(user_id):
        keyboard_buttons.append([KeyboardButton(text="➕ Добавить приложение")])
    
    if Config.is_editor(user_id):
        keyboard_buttons.append([KeyboardButton(text="✏️ Изменить приложение")])
    
    if Config.is_moderator(user_id):
        keyboard_buttons.append([KeyboardButton(text="🗑️ Удалить приложение")])
    
    if Config.is_full_admin(user_id):
        keyboard_buttons.append([KeyboardButton(text="➕ Добавить канал"), 
                                KeyboardButton(text="🗑️ Удалить канал")])
        keyboard_buttons.append([KeyboardButton(text="✏️ Изменить канал")])
    
    if Config.is_full_admin(user_id):
        keyboard_buttons.append([KeyboardButton(text="🎁 Управление розыгрышами")])
    
    if Config.is_owner(user_id):
        keyboard_buttons.append([KeyboardButton(text="👥 Управление админами")])
    
    if Config.is_full_admin(user_id):
        keyboard_buttons.append([KeyboardButton(text="📝 Список предложений")])

    if Config.is_full_admin(user_id):
        keyboard_buttons.append([KeyboardButton(text="📂 Архив")])
    
    if Config.is_moderator(user_id):
        keyboard_buttons.append([KeyboardButton(text="📊 Статистика")])

    # Кнопка для просмотра сообщений пользователей (pending_messages) — только для менеджеров и выше
    if Config.is_manager(user_id):
        keyboard_buttons.append([KeyboardButton(text="📬 Сообщения пользователей")])
    
    # Кнопка назад всегда в конце
    keyboard_buttons.append([KeyboardButton(text="🔙 Назад")])
    
    return ReplyKeyboardMarkup(keyboard=keyboard_buttons, resize_keyboard=True)

def get_admin_management_menu() -> InlineKeyboardMarkup:
    """Меню управления администраторами"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить админа", callback_data="admin_add"),
             InlineKeyboardButton(text="➕ Добавить менеджера", callback_data="manager_add")],
            [InlineKeyboardButton(text="➖ Удалить админа", callback_data="admin_remove")],
            [InlineKeyboardButton(text="⚙️ Изменить права", callback_data="admin_change_level"),
             InlineKeyboardButton(text="📋 Список админов", callback_data="admin_list")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin")]
        ]
    )
# === Добавление менеджера ===
@dp.callback_query(F.data == "manager_add")
async def manager_add_callback(callback: types.CallbackQuery, state: FSMContext):
    if not Config.is_owner(callback.from_user.id):
        await callback.answer("⛔ Только владелец может добавлять менеджера.", show_alert=True)
        return
    await callback.message.answer("Введите ID пользователя, которого хотите назначить менеджером:")
    await state.set_state(AdminStates.add_manager_id)
    await state.update_data(manager_add=True)

@dp.message(AdminStates.add_manager_id)
async def manager_add_id_handler(message: types.Message, state: FSMContext):
    try:
        data = await state.get_data()
        if not data.get("manager_add"):
            return  # Не наш сценарий
        try:
            user_id = int(message.text.strip())
        except Exception:
            await message.answer("❌ Введите корректный числовой ID пользователя.")
            return
        admins = Config.load_admins()
        for admin in admins:
            if admin['id'] == user_id:
                await message.answer("❌ Этот пользователь уже администратор или менеджер.")
                await state.clear()
                return
        Config.add_admin(user_id, level=Config.ADMIN_LEVELS['manager'])
        await message.answer(f"✅ Пользователь {user_id} назначен менеджером.")
    except Exception as e:
        logger.exception(f"Unexpected error in manager_add_id_handler: {e}")
        try:
            await message.answer("❌ Внутренняя ошибка при назначении менеджера. Посмотрите логи.")
        except Exception:
            pass
    finally:
        try:
            await state.clear()
        except Exception:
            pass

def get_giveaways_management_menu() -> InlineKeyboardMarkup:
    """Меню управления розыгрышами"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать розыгрыш", callback_data="giveaway_add"),
             InlineKeyboardButton(text="✏️ Изменить розыгрыш", callback_data="giveaway_edit")],
            [InlineKeyboardButton(text="🗑️ Удалить розыгрыш", callback_data="giveaway_delete"),
             InlineKeyboardButton(text="🏁 Завершить розыгрыш", callback_data="giveaway_end")],
            [InlineKeyboardButton(text="📋 Список розыгрышей", callback_data="giveaway_list")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin")]
        ]
    )

def get_giveaway_action_menu(giveaway_id: int, user_id: int = None) -> InlineKeyboardMarkup:
    """Меню действий для розыгрыша"""
    is_participant = user_id and db.is_participant(giveaway_id, user_id)
    
    if is_participant:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Вы участвуете", callback_data=f"already_participating:{giveaway_id}")],
                [InlineKeyboardButton(text="🔙 Назад к розыгрышам", callback_data="back_to_giveaways_user")]
            ]
        )
    else:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🎯 Участвовать", callback_data=f"participate:{giveaway_id}")],
                [InlineKeyboardButton(text="🔙 Назад к розыгрышам", callback_data="back_to_giveaways_user")]
            ]
        )


def build_app_keyboard(app: Dict, app_id: int = None) -> Optional[InlineKeyboardMarkup]:
    """Построить inline-клавиатуру для приложения: кнопки на пост и на файл (если есть).
    Кнопка для локального файла отправляется через callback `get_file:<id>`,
    внешние ссылки открываются через `url`.
    """
    buttons = []

    # Ссылка на пост
    post_link = app.get('post_link')
    if post_link:
        buttons.append(InlineKeyboardButton(text="📱 Перейти к посту", url=post_link))

    # Внешняя ссылка на файл
    file_link = app.get('file_link')
    if file_link:
        # вместо прямой ссылки — даём кнопку, которая вызовет скачивание и отправку файла
        if app_id:
            buttons.append(InlineKeyboardButton(text="📁 Получить файл", callback_data=f"get_file_external:{app_id}"))
        else:
            buttons.append(InlineKeyboardButton(text="📁 Скачать файл", url=file_link))
    else:
        # Попытка найти локальный файл по полям app
        local_candidates = []
        if app.get('file_path'):
            local_candidates.append(app.get('file_path'))
        if app.get('file_name'):
            local_candidates.append(os.path.join('files', app.get('file_name')))
        # несколько стандартных вариантов по id
        if app_id:
            local_candidates.append(os.path.join('files', str(app_id)))
            local_candidates.append(os.path.join('files', f"{app_id}.apk"))
            local_candidates.append(os.path.join('files', f"{app_id}.zip"))

        found_local = None
        for p in local_candidates:
            if p and os.path.exists(p):
                found_local = p
                break

        if found_local and app_id:
            buttons.append(InlineKeyboardButton(text="📁 Получить файл", callback_data=f"get_file:{app_id}"))

    if not buttons:
        return None

    # Конвертируем в структуру inline_keyboard: по одной кнопке в строке
    inline_keyboard = [[b] for b in buttons]
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)

def get_suggestion_type_menu() -> InlineKeyboardMarkup:
    """Меню выбора типа предложения"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💡 Предложить идею", callback_data="suggest_idea"),
             InlineKeyboardButton(text="🎮 Предложить игру", callback_data="suggest_game")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
        ]
    )

def get_channels_menu() -> ReplyKeyboardMarkup:
    """Меню каналов"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📢 Наши каналы")],
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )

def get_giveaways_menu() -> ReplyKeyboardMarkup:
    """Меню розыгрышей"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎁 Активные розыгрыши"), KeyboardButton(text="🏆 Победители")],
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )

def get_jobs_menu() -> InlineKeyboardMarkup:
    """Меню вакансий"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👔 Работа постером", callback_data="job_poster"),
             InlineKeyboardButton(text="✏️ Работа редактором", callback_data="job_editor")],
            [InlineKeyboardButton(text="🛡️ Работа модератором", callback_data="job_moderator")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
        ]
    )

def get_cancel_button() -> ReplyKeyboardMarkup:
    """Кнопка отмены"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="❌ Отмена"), KeyboardButton(text="🔙 В главное меню")]
        ],
        resize_keyboard=True
    )

def get_back_button() -> ReplyKeyboardMarkup:
    """Кнопка назад"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔙 Назад")]
        ],
        resize_keyboard=True
    )

def get_genre_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура с жанрами"""
    keyboard = []
    for i in range(0, len(Config.GENRES), 2):
        row = []
        row.append(KeyboardButton(text=Config.GENRES[i]))
        if i + 1 < len(Config.GENRES):
            row.append(KeyboardButton(text=Config.GENRES[i + 1]))
        keyboard.append(row)
    keyboard.append([KeyboardButton(text="🔙 Назад")])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def build_genre_inline_for_add() -> InlineKeyboardMarkup:
    """Inline клавиатура для выбора жанра в процессе добавления приложения"""
    buttons = []
    for g in Config.GENRES:
        buttons.append([InlineKeyboardButton(text=g, callback_data=f"addapp_genre:{g}")])
    # Добавим кнопку назад
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="addapp_genre_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_size_inline_for_add() -> InlineKeyboardMarkup:
    buttons = []
    for s in Config.SIZES:
        buttons.append([InlineKeyboardButton(text=s, callback_data=f"addapp_size:{s}")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="addapp_size_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def build_inline_back(callback_data: str) -> InlineKeyboardMarkup:
    """Универсальная inline-кнопка назад с заданным callback_data"""
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data=callback_data)]])

def get_size_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура с размерами"""
    keyboard = []
    for size in Config.SIZES:
        keyboard.append([KeyboardButton(text=size)])
    keyboard.append([KeyboardButton(text="🔙 Назад")])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

# ================== ОСНОВНЫЕ КОМАНДЫ ==================

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Команда /start"""
    try:
        welcome_text = (
            "🎮 <b>Добро пожаловать в GameHub Bot!</b>\n\n"
            "🎯 <b>Основные возможности:</b>\n"
            "• 🔍 Поиск игр и приложений\n"
            "• 🎲 Случайная игра на вечер\n"
            "• 🎁 Участие в розыгрышах\n"
            "• 💡 Предложить идею или игру\n"
            "• 💼 Вакансии в нашей команде\n"
            "• 🔒 Приватный доступ к эксклюзивам\n\n"
            "Выберите действие в меню ниже:"
        )
        await message.answer(welcome_text, parse_mode='HTML', reply_markup=get_main_menu(message.from_user.id))
        # Регистрируем пользователя как известного (используется для рассылок)
        try:
            db.add_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
        except Exception as e:
            logger.error(f"Не удалось сохранить пользователя: {e}")
    except Exception as e:
        logger.error(f"Ошибка в /start: {e}")
        await message.answer("Произошла ошибка. Попробуйте еще раз.")

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Команда /help"""
    help_text = (
        "ℹ️ <b>Помощь по использованию GameHub:</b>\n\n"
        "🎮 <b>Основные функции:</b>\n"
        "• <b>🔍 Поиск</b> - поиск приложений по разным критериям\n"
        "• <b>🎲 Рандомная игра</b> - случайное приложение\n"
        "• <b>🎁 Розыгрыши</b> - участие в конкурсах\n"
        "• <b>📢 Каналы</b> - наши каналы и группы\n"
        "• <b>💡 Предложить игру</b> - предложить новую игру\n"
        "• <b>💼 Вакансии</b> - работа в нашей команде\n\n"
        "⚙️ <b>Для администраторов:</b>\n"
        "Доступна админ-панель для управления контентом\n\n"
        "<i>По всем вопросам обращайтесь к администраторам.</i>"
    )
    await message.answer(help_text, parse_mode='HTML')

@dp.message(F.text == "ℹ️ Помощь")
async def help_handler(message: types.Message):
    """Обработчик кнопки помощи"""
    await cmd_help(message)

@dp.message(F.text == "🔙 Назад")
async def back_to_main(message: types.Message):
    """Возврат в главное меню"""
    await cmd_start(message)

@dp.message(F.text == "⚙️ Админ-панель")
async def admin_menu(message: types.Message):
    """Админ-панель"""
    if not Config.is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа к админ-панели.")
        return
    
    admin_level = Config.get_admin_level(message.from_user.id)
    role_name = Config.get_role_name(admin_level)
    
    await message.answer(
        f"⚙️ <b>Админ-панель GameHub</b>\n"
        f"👤 <b>Ваша роль:</b> {role_name}\n\n"
        f"Выберите действие:", 
        parse_mode='HTML', 
        reply_markup=get_admin_menu(message.from_user.id)
    )

@dp.message(F.text == "🔙 В главное меню")
async def back_to_main_from_cancel(message: types.Message):
    """Возврат в главное меню из отмены"""
    await cmd_start(message)

# ================== ОБРАБОТЧИКИ ГЛАВНОГО МЕНЮ ==================

@dp.message(F.text == "🔍 Поиск")
async def search_menu_handler(message: types.Message):
    """Обработчик кнопки поиска"""
    await message.answer("🔍 <b>Выберите тип поиска:</b>", parse_mode='HTML', reply_markup=get_search_menu())

@dp.message(F.text == "🎲 Рандомная игра")
async def random_game_handler(message: types.Message):
    """Обработчик кнопки рандомной игры"""
    try:
        app = db.get_random_app()
        if app:
            text = (
                f"🎲 <b>Случайная игра:</b>\n\n"
                f"📱 <b>{app.get('name', 'Без названия')}</b>\n"
                f"🎮 <b>Жанр:</b> {app.get('genre', 'Не указан')}\n"
                f"📦 <b>Размер:</b> {app.get('size_category', 'Не указан')}\n\n"
                f"📄 <b>Описание:</b>\n{app.get('description', 'Нет описания')}\n\n"
                f"🔗 <b>Ссылка на пост:</b> {app.get('post_link', 'Нет ссылки')}"
            )
            # Клавиатура: пост и/или файл
            keyboard = build_app_keyboard(app, app.get('id'))
            await message.answer(text, parse_mode='HTML', reply_markup=keyboard)
        else:
            text = "📭 Пока нет приложений в базе. Администраторы скоро добавят контент!"
            await message.answer(text, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Ошибка в random_game_handler: {e}")
        await message.answer("❌ Произошла ошибка при поиске случайной игры.")

@dp.message(F.text == "🎁 Розыгрыши")
async def giveaways_handler(message: types.Message):
    """Обработчик кнопки розыгрышей"""
    await message.answer(
        "🎁 <b>Розыгрыши и конкурсы</b>\n\n"
        "Участвуйте в наших розыгрышах и выигрывайте призы!\n"
        "Для участия выберите активный розыгрыш и нажмите 'Участвовать'.",
        parse_mode='HTML',
        reply_markup=get_giveaways_menu()
    )

@dp.message(F.text == "🎁 Активные розыгрыши")
async def show_active_giveaways(message: types.Message):
    """Показать активные розыгрыши с возможностью выбора"""
    try:
        active_giveaways = db.get_active_giveaways()
        
        if not active_giveaways:
            await message.answer(
                "🎁 <b>Активные розыгрыши</b>\n\n"
                "В данный момент нет активных розыгрышей.\n"
                "Следите за обновлениями! Новые розыгрыши появляются регулярно.",
                parse_mode='HTML'
            )
            return
        
        # Создаем клавиатуру с активными розыгрышами
        builder = InlineKeyboardBuilder()
        
        for giveaway in active_giveaways[:10]:
            title = giveaway.get('title', 'Без названия')[:30]
            builder.add(InlineKeyboardButton(
                text=f"🎁 {title}",
                callback_data=f"view_giveaway:{giveaway.get('id')}"
            ))
        
        builder.adjust(1)
        builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main"))
        
        await message.answer(
            "🎁 <b>Активные розыгрыши</b>\n\n"
            "Выберите розыгрыш для участия:",
            parse_mode='HTML',
            reply_markup=builder.as_markup()
        )
    except Exception as e:
        logger.error(f"Ошибка в show_active_giveaways: {e}")
        await message.answer("❌ Произошла ошибка при загрузке розыгрышей.")

@dp.message(F.text == "🏆 Победители")
async def winners_handler(message: types.Message):
    """Показать победителей розыгрышей"""
    try:
        ended_giveaways = db.get_ended_giveaways()
        
        if not ended_giveaways:
            await message.answer(
                "🏆 <b>Победители розыгрышей</b>\n\n"
                "Пока нет завершенных розыгрышей.\n"
                "Станьте первым победителем!",
                parse_mode='HTML'
            )
            return
        
        # Формируем сообщение с победителями
        winners_text = "🏆 <b>Победители розыгрышей:</b>\n\n"
        
        for i, giveaway in enumerate(ended_giveaways[:5], 1):
            winner = giveaway.get('winner', {})
            winner_name = winner.get('username', winner.get('first_name', 'Неизвестно'))
            
            winners_text += (
                f"{i}. 🎁 <b>{giveaway.get('title', 'Без названия')}</b>\n"
                f"   🏆 <b>Приз:</b> {giveaway.get('prize', 'Не указан')}\n"
                f"   👑 <b>Победитель:</b> {winner_name}\n"
                f"   📅 <b>Дата окончания:</b> {giveaway.get('end_datetime', 'Не указано')}\n\n"
            )
        
        if len(ended_giveaways) > 5:
            winners_text += f"<i>Показано 5 из {len(ended_giveaways)} завершенных розыгрышей</i>"
        
        await message.answer(winners_text, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Ошибка в winners_handler: {e}")
        await message.answer("❌ Произошла ошибка при загрузке списка победителей.")

@dp.callback_query(F.data.startswith("view_giveaway:"))
async def view_giveaway_details(callback: types.CallbackQuery):
    """Просмотр деталей розыгрыша"""
    try:
        giveaway_id = int(callback.data.split(":")[1])
        giveaway = db.get_giveaway_by_id(giveaway_id)
        
        if not giveaway:
            await callback.answer("Розыгрыш не найден")
            return
        
        # Проверяем, не завершен ли розыгрыш
        if giveaway.get('ended', False):
            winner = giveaway.get('winner', {})
            winner_name = winner.get('username', winner.get('first_name', 'Победитель'))
            
            await callback.message.answer(
                f"🏁 <b>Розыгрыш завершен</b>\n\n"
                f"🎁 <b>{giveaway.get('title', 'Без названия')}</b>\n"
                f"🏆 <b>Приз:</b> {giveaway.get('prize', 'Не указан')}\n"
                f"👑 <b>Победитель:</b> {winner_name}\n"
                f"👥 <b>Участников:</b> {len(giveaway.get('participants', []))}\n\n"
                f"Спасибо всем за участие!",
                parse_mode='HTML'
            )
            await callback.answer()
            return
        
        # Проверяем время окончания
        end_datetime_str = giveaway.get('end_datetime', '')
        try:
            end_datetime = datetime.strptime(end_datetime_str, "%d.%m.%Y %H:%M")
            if datetime.now() >= end_datetime:
                # Автоматически завершаем розыгрыш
                db.end_giveaway(giveaway_id)
                await callback.message.answer(
                    "🏁 <b>Розыгрыш завершен</b>\n\n"
                    "Время участия в этом розыгрыше истекло.\n"
                    "Результаты будут опубликованы в ближайшее время.",
                    parse_mode='HTML'
                )
                await callback.answer()
                return
        except:
            pass
        
        # Формируем информацию о розыгрыше
        time_remaining = format_time_remaining(giveaway.get('end_datetime', ''))
        
        text = (
            f"🎁 <b>{giveaway.get('title', 'Без названия')}</b>\n\n"
            f"📝 <b>Описание:</b>\n{giveaway.get('description', 'Нет описания')}\n\n"
            f"🏆 <b>Приз:</b> {giveaway.get('prize', 'Не указан')}\n"
            f"📅 <b>Окончание:</b> {giveaway.get('end_datetime', 'Не указано')}\n"
            f"{time_remaining}\n"
            f"👥 <b>Участников:</b> {len(giveaway.get('participants', []))}"
        )
        
        # Получаем меню действий
        keyboard = get_giveaway_action_menu(giveaway_id, callback.from_user.id)
        
        await callback.message.answer(text, parse_mode='HTML', reply_markup=keyboard)
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в view_giveaway_details: {e}")
        await callback.message.answer("❌ Произошла ошибка.")
        await callback.answer()

@dp.callback_query(F.data.startswith("participate:"))
async def participate_in_giveaway(callback: types.CallbackQuery):
    """Участие в розыгрыше"""
    try:
        giveaway_id = int(callback.data.split(":")[1])
        giveaway = db.get_giveaway_by_id(giveaway_id)
        
        if not giveaway:
            await callback.answer("Розыгрыш не найден")
            return
        
        # Проверяем, не завершен ли розыгрыш
        if giveaway.get('ended', False):
            await callback.message.answer("❌ Этот розыгрыш уже завершен.")
            await callback.answer()
            return
        
        # Добавляем участника
        success = db.add_participant(
            giveaway_id,
            callback.from_user.id,
            callback.from_user.username or "",
            callback.from_user.first_name or "Пользователь"
        )
        
        if success:
            # Обновляем информацию о розыгрыше
            giveaway = db.get_giveaway_by_id(giveaway_id)
            time_remaining = format_time_remaining(giveaway.get('end_datetime', ''))
            
            text = (
                f"🎉 <b>Вы успешно участвуете в розыгрыше!</b>\n\n"
                f"🎁 <b>{giveaway.get('title', 'Без названия')}</b>\n"
                f"🏆 <b>Приз:</b> {giveaway.get('prize', 'Не указан')}\n"
                f"📅 <b>Окончание:</b> {giveaway.get('end_datetime', 'Не указано')}\n"
                f"{time_remaining}\n"
                f"👥 <b>Участников:</b> {len(giveaway.get('participants', []))}\n\n"
                f"<i>Удачи в розыгрыше! Результаты будут объявлены после окончания.</i>"
            )
            
            await callback.message.answer(text, parse_mode='HTML')
        else:
            await callback.message.answer("❌ Вы уже участвуете в этом розыгрыше.")
        
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в participate_in_giveaway: {e}")
        await callback.message.answer("❌ Произошла ошибка.")
        await callback.answer()


@dp.callback_query(F.data.startswith("get_file:"))
async def send_app_file(callback: types.CallbackQuery):
    """Отправляет локальный файл приложения по нажатию кнопки.
    Ожидается, что запись приложения может содержать `file_path` или `file_name`.
    Также пробуем несколько стандартных вариантов в папке `files/`.
    """
    try:
        # Блокировка: предотвращаем параллельные/повторные запросы от одного пользователя
        uid = callback.from_user.id
        if recent_sending.get(uid):
            await callback.answer("⏳ Ваш предыдущий запрос всё ещё обрабатывается.", show_alert=True)
            return
        recent_sending[uid] = True

        app_id = int(callback.data.split(":")[1])
        app = db.get_app_by_id(app_id)
        if not app:
            await callback.answer("❌ Приложение не найдено")
            return

        candidates = []
        if app.get('file_path'):
            candidates.append(app.get('file_path'))
        if app.get('file_name'):
            candidates.append(os.path.join('files', app.get('file_name')))
        candidates.append(os.path.join('files', str(app_id)))
        candidates.append(os.path.join('files', f"{app_id}.apk"))
        candidates.append(os.path.join('files', f"{app_id}.zip"))

        found = None
        for p in candidates:
            if p and os.path.exists(p):
                found = p
                break

        if not found:
            await callback.answer("❌ Файл не найден на сервере.", show_alert=True)
            return

        # Флаг: был ли уже отправлен файл в ходе обработки (чтобы предотвратить дубли)
        already_sent = False

        # Если указан file_link на t.me — пробуем переслать сам файл из этого сообщения (приоритет)
        file_link = app.get('file_link', '')
        # Отключаем server-side пересылку (copy/forward) для t.me — принудительно скачиваем файл
        if False and file_link and 't.me' in file_link:
            try:
                parsed = urlparse(file_link)
                parts = parsed.path.strip('/').split('/')
                if parts:
                    if parts[0] == 'c' and len(parts) >= 3:
                        channel_part = parts[1]
                        msg_id = int(parts[2])
                        from_chat_id = int(f"-100{channel_part}")
                    elif len(parts) >= 2:
                        username = parts[0]
                        msg_id = int(parts[1])
                        from_chat_id = f"@{username.lstrip('@')}"
                    else:
                        from_chat_id = None
                        msg_id = None

                    if from_chat_id and msg_id:
                        try:
                            copied_msg = None
                            try:
                                copied_msg = await callback.bot.copy_message(callback.from_user.id, from_chat_id, msg_id)
                                logger.info(f"File post (msg {msg_id}) from file_link copied to user {callback.from_user.id}")
                                logger.info(f"ACTION: copy_message succeeded for msg={msg_id} user={callback.from_user.id}")
                                try:
                                    attrs = {k: bool(getattr(copied_msg, k, None)) for k in ['document','photo','video','animation','audio','voice','caption','text']}
                                    logger.debug(f"copied_msg attrs (file_link, send_app_file): {attrs}")
                                except Exception:
                                    logger.debug("copied_msg has no detailed attrs (file_link, send_app_file)")
                                if copied_msg and (getattr(copied_msg, 'document', None) or getattr(copied_msg, 'photo', None) or getattr(copied_msg, 'video', None) or getattr(copied_msg, 'animation', None) or getattr(copied_msg, 'audio', None) or getattr(copied_msg, 'voice', None)):
                                    try:
                                        await callback.bot.edit_message_caption(chat_id=callback.from_user.id, message_id=copied_msg.message_id, caption='')
                                    except Exception:
                                        pass
                                    # Сохраним уникальный id отправленного файла (ниже записываем с timestamp)
                                    already_sent = True
                                    # записываем уникальный id и отметку времени
                                    try:
                                        if getattr(copied_msg, 'document', None):
                                            recent_sent_files[uid] = (copied_msg.document.file_unique_id, time.time())
                                        elif getattr(copied_msg, 'photo', None) and isinstance(copied_msg.photo, list) and copied_msg.photo:
                                            recent_sent_files[uid] = (copied_msg.photo[-1].file_unique_id, time.time())
                                        elif getattr(copied_msg, 'video', None):
                                            recent_sent_files[uid] = (copied_msg.video.file_unique_id, time.time())
                                    except Exception:
                                        pass
                                    await callback.answer()
                                    recent_sending[uid] = False
                                    return
                            except Exception as e:
                                logger.info(f"copy_message по file_link не сработал в send_app_file: {e}, попробуем forward_message")

                            if not copied_msg:
                                try:
                                    forwarded_msg = await callback.bot.forward_message(callback.from_user.id, from_chat_id, msg_id)
                                    logger.info(f"File post (msg {msg_id}) forwarded to user {callback.from_user.id}")
                                    logger.info(f"ACTION: forward_message succeeded for msg={msg_id} user={callback.from_user.id}")
                                    try:
                                        attrs = {k: bool(getattr(forwarded_msg, k, None)) for k in ['document','photo','video','animation','audio','voice','caption','text']}
                                        logger.debug(f"forwarded_msg attrs (file_link, send_app_file): {attrs}")
                                    except Exception:
                                        logger.debug("forwarded_msg has no detailed attrs (file_link, send_app_file)")
                                    if forwarded_msg and (getattr(forwarded_msg, 'document', None) or getattr(forwarded_msg, 'photo', None) or getattr(forwarded_msg, 'video', None) or getattr(forwarded_msg, 'animation', None) or getattr(forwarded_msg, 'audio', None) or getattr(forwarded_msg, 'voice', None)):
                                        try:
                                            await callback.bot.edit_message_caption(chat_id=callback.from_user.id, message_id=forwarded_msg.message_id, caption='')
                                        except Exception:
                                            pass
                                        # Сохранение с timestamp ниже
                                        already_sent = True
                                        try:
                                            if getattr(forwarded_msg, 'document', None):
                                                recent_sent_files[uid] = (forwarded_msg.document.file_unique_id, time.time())
                                            elif getattr(forwarded_msg, 'photo', None) and isinstance(forwarded_msg.photo, list) and forwarded_msg.photo:
                                                recent_sent_files[uid] = (forwarded_msg.photo[-1].file_unique_id, time.time())
                                            elif getattr(forwarded_msg, 'video', None):
                                                recent_sent_files[uid] = (forwarded_msg.video.file_unique_id, time.time())
                                        except Exception:
                                            pass
                                        await callback.answer()
                                        recent_sending[uid] = False
                                        return
                                except Exception as e:
                                    logger.info(f"forward_message по file_link не сработал в send_app_file: {e}")
                        except Exception as e:
                            logger.debug(f"Ошибка при попытке переслать файл по file_link в send_app_file: {e}")
            except Exception as e:
                logger.debug(f"Не удалось распарсить file_link для пересылки в send_app_file: {e}")

        

        # Если указан file_link — приоритетно отправляем файл, на который он указывает.
        # Не отправляем локальный `found`, если `file_link` присутствует.
        file_link = app.get('file_link')
        if file_link:
            # Если file_link — t.me ссылка, попытки copy/forward уже были выше и не сработали.
            # В этом случае НЕ пересылаем локальный файл, а сообщаем об ошибке пересылки.
            if 't.me' in file_link:
                await callback.answer('❌ Файл в канале найден, но не удалось переслать его. Пожалуйста, свяжитесь с администрацией.')
                return

            # Иначе — file_link внешняя ссылка: скачиваем и отправляем её пользователю (в ЛС при возможности)
            tmp_fd, tmp_path = None, None
            try:
                tmp_dir = os.path.join('files', 'tmp')
                os.makedirs(tmp_dir, exist_ok=True)
                import tempfile
                fd, tmp_path = tempfile.mkstemp(dir=tmp_dir, prefix=f"app_{app_id}_", suffix=os.path.splitext(file_link)[1] or '')
                os.close(fd)
                async with aiohttp.ClientSession() as session:
                    async with session.get(file_link) as resp:
                        if resp.status != 200:
                            await callback.answer(f"❌ Не удалось скачать файл (HTTP {resp.status}).", show_alert=True)
                            return
                        # Попытка извлечь имя файла из заголовка Content-Disposition
                        filename = None
                        try:
                            cd = resp.headers.get('content-disposition')
                            if cd:
                                import re
                                m = re.search(r"filename\*?=([^;]+)", cd)
                                if m:
                                    fn = m.group(1).strip()
                                    if fn.lower().startswith("utf-") or "'" in fn:
                                        # возможно формат filename*=utf-8''name
                                        parts = fn.split("''")
                                        if len(parts) > 1:
                                            fn = parts[-1]
                                    filename = fn.strip('"')
                        except Exception:
                            filename = None

                        if not filename:
                            filename = os.path.basename(urlparse(file_link).path) or f"app_{app_id}{os.path.splitext(file_link)[1] or ''}"

                        with open(tmp_path, 'wb') as f:
                            while True:
                                chunk = await resp.content.read(1024 * 64)
                                if not chunk:
                                    break
                                f.write(chunk)

                # Отправляем только файл (без превью/текста), но только если ранее не переслали его напрямую
                sent_to_pm = False
                try:
                    # Если недавно был переслан тот же файл — пропускаем отправку
                    recent = recent_sent_files.get(callback.from_user.id)
                    if recent and (time.time() - recent[1]) < 8:
                        logger.info(f"Skipping send: recent file sent to user {callback.from_user.id} {recent}")
                        sent_to_pm = True
                    elif not already_sent:
                        logger.info(f"ACTION: sending temp file to user {callback.from_user.id} tmp_path={tmp_path} filename={filename}")
                        await callback.bot.send_document(callback.from_user.id, FSInputFile(tmp_path, filename=filename))
                        sent_to_pm = True
                        already_sent = True
                except Exception as e:
                    logger.warning(f"Не удалось отправить внешний файл (file_link) в ЛС: {e}")

                if not sent_to_pm:
                    try:
                        if not already_sent:
                            await callback.message.answer_document(FSInputFile(tmp_path, filename=filename))
                            already_sent = True
                    except Exception as e2:
                        logger.error(f"Ошибка при fallback отправке внешнего файла: {e2}")
                        await callback.answer("❌ Не удалось отправить файл.")

            finally:
                try:
                    if tmp_path and os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except Exception:
                    pass
            await callback.answer()
            return

        # Если file_link не указан — отправляем локальный файл `found` как раньше
        preview_text = (
            f"🎮 <b>{app.get('name', 'Без названия')}</b>\n"
            f"🎮 <b>Жанр:</b> {app.get('genre', 'Не указан')}\n"
            f"📦 <b>Размер:</b> {app.get('size_category', 'Не указан')}\n\n"
            f"📄 <b>Описание:</b>\n{app.get('description', 'Нет описания')}\n\n"
            f"🔗 <b>Ссылка на пост:</b> {app.get('post_link', 'Не указана')}"
        )

        # Кнопки превью (если есть пост)
        preview_buttons = []
        if app.get('post_link'):
            preview_buttons.append([InlineKeyboardButton(text="📱 Перейти к посту", url=app.get('post_link'))])
        preview_kb = InlineKeyboardMarkup(inline_keyboard=preview_buttons) if preview_buttons else None

        # Отправляем локальный файл
        sent_to_pm = False
        try:
            msg_preview = await callback.bot.send_message(callback.from_user.id, preview_text, parse_mode='HTML', reply_markup=preview_kb)
            logger.info(f"ACTION: sending local file to user {callback.from_user.id} path={found}")
            # Если недавно был переслан тот же файл — пропускаем отправку
            recent = recent_sent_files.get(callback.from_user.id)
            if recent and (time.time() - recent[1]) < 8:
                logger.info(f"Skipping local send: recent file sent to user {callback.from_user.id} {recent}")
                doc_msg = None
            else:
                doc_msg = await callback.bot.send_document(callback.from_user.id, FSInputFile(found))
            # Сохраним file_unique_id как последнее отправленное пользователю
            try:
                if doc_msg and getattr(doc_msg, 'document', None):
                    recent_sent_files[callback.from_user.id] = (doc_msg.document.file_unique_id, time.time())
                elif doc_msg and getattr(doc_msg, 'photo', None) and isinstance(doc_msg.photo, list) and doc_msg.photo:
                    recent_sent_files[callback.from_user.id] = (doc_msg.photo[-1].file_unique_id, time.time())
                elif doc_msg and getattr(doc_msg, 'video', None):
                    recent_sent_files[callback.from_user.id] = (doc_msg.video.file_unique_id, time.time())
            except Exception:
                pass
            sent_to_pm = True
            try:
                await callback.message.answer("✅ Описание и файл отправлены вам в личные сообщения.")
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"Не удалось отправить превью/файл в ЛС: {e}")

        if not sent_to_pm:
            # fallback: отправляем превью и файл в текущий чат
            try:
                try:
                    if preview_kb:
                        await callback.message.answer(preview_text, parse_mode='HTML', reply_markup=preview_kb)
                    else:
                        await callback.message.answer(preview_text, parse_mode='HTML')
                except Exception:
                    pass
                await callback.message.answer_document(FSInputFile(found))
                await callback.message.answer("⚠️ Не удалось отправить в ЛС; превью и файл отправлены здесь.")
            except Exception as e2:
                logger.error(f"Ошибка при fallback отправке превью/файла: {e2}")
                await callback.answer("❌ Не удалось отправить файл.")
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в send_app_file: {e}")
        await callback.answer("❌ Произошла ошибка при отправке файла.")
    finally:
        try:
            recent_sending[uid] = False
        except Exception:
            pass


@dp.callback_query(F.data.startswith("get_file_external:"))
async def send_external_file(callback: types.CallbackQuery):
    """Скачивает внешний файл по URL и отправляет пользователю (ЛС), с fallback в текущий чат."""
    try:
        uid = callback.from_user.id
        # Блокировка: предотвращаем параллельные/повторные запросы от одного пользователя
        if recent_sending.get(uid):
            await callback.answer("⏳ Ваш предыдущий запрос всё ещё обрабатывается.", show_alert=True)
            return
        recent_sending[uid] = True

        app_id = int(callback.data.split(":")[1])
        app = db.get_app_by_id(app_id)
        if not app:
            await callback.answer("❌ Приложение не найдено")
            return

        file_url = app.get('file_link')
        if not file_url or not file_url.startswith('http'):
            await callback.answer("❌ Нет корректной внешней ссылки на файл.")
            return

        logger.debug(f"send_external_file: app_id={app_id} file_link={app.get('file_link')} post_link={app.get('post_link')}")

        # Если file_link указывает на t.me — попробуем переслать медиа сообщением (copy/forward).
        # Если переслать не удастся — FALLBACK к скачиванию ниже (и пропускаем send by URL).
        file_link = app.get('file_link', '')
        post_link = app.get('post_link', '')
        tried_tme = False
        sent_via_forward = False
        skip_send_by_url = False
        if file_link and ('t.me' in file_link or 'telegram.me' in file_link):
            tried_tme = True
            try:
                parsed = urlparse(file_link)
                parts = parsed.path.strip('/').split('/')
                if parts:
                    if parts[0] == 'c' and len(parts) >= 3:
                        channel_part = parts[1]
                        msg_id = int(parts[2])
                        from_chat_id = int(f"-100{channel_part}")
                    elif len(parts) >= 2:
                        username = parts[0]
                        msg_id = int(parts[1])
                        from_chat_id = f"@{username.lstrip('@')}"
                    else:
                        from_chat_id = None
                        msg_id = None

                    if from_chat_id and msg_id:
                        try:
                            copied_msg = None
                            sent_via_forward = False
                            try:
                                copied_msg = await callback.bot.copy_message(callback.from_user.id, from_chat_id, msg_id)
                                logger.info(f"File post (msg {msg_id}) from file_link copied to user {callback.from_user.id}")
                                # Логируем атрибуты скопированного сообщения
                                try:
                                    attrs = {k: bool(getattr(copied_msg, k, None)) for k in ['document','photo','video','animation','audio','voice','caption','text']}
                                    logger.debug(f"copied_msg attrs (file_link): {attrs}")
                                except Exception:
                                    logger.debug("copied_msg has no detailed attrs (file_link)")
                                if copied_msg and (getattr(copied_msg, 'document', None) or getattr(copied_msg, 'photo', None) or getattr(copied_msg, 'video', None) or getattr(copied_msg, 'animation', None) or getattr(copied_msg, 'audio', None) or getattr(copied_msg, 'voice', None)):
                                    try:
                                        await callback.bot.edit_message_caption(chat_id=callback.from_user.id, message_id=copied_msg.message_id, caption='')
                                    except Exception:
                                        pass
                                    sent_via_forward = True
                                    # записываем уникальный id и отметку времени
                                    try:
                                        if getattr(copied_msg, 'document', None):
                                            recent_sent_files[uid] = (copied_msg.document.file_unique_id, time.time())
                                        elif getattr(copied_msg, 'photo', None) and isinstance(copied_msg.photo, list) and copied_msg.photo:
                                            recent_sent_files[uid] = (copied_msg.photo[-1].file_unique_id, time.time())
                                        elif getattr(copied_msg, 'video', None):
                                            recent_sent_files[uid] = (copied_msg.video.file_unique_id, time.time())
                                    except Exception:
                                        pass
                                    await callback.answer()
                                    recent_sending[uid] = False
                                    return
                            except Exception as e:
                                logger.info(f"copy_message по file_link не сработал: {e}, попробуем forward_message")

                            if not copied_msg:
                                try:
                                    forwarded_msg = await callback.bot.forward_message(callback.from_user.id, from_chat_id, msg_id)
                                    logger.info(f"File post (msg {msg_id}) forwarded to user {callback.from_user.id}")
                                    try:
                                        attrs = {k: bool(getattr(forwarded_msg, k, None)) for k in ['document','photo','video','animation','audio','voice','caption','text']}
                                        logger.debug(f"forwarded_msg attrs (file_link): {attrs}")
                                    except Exception:
                                        logger.debug("forwarded_msg has no detailed attrs (file_link)")
                                    if forwarded_msg and (getattr(forwarded_msg, 'document', None) or getattr(forwarded_msg, 'photo', None) or getattr(forwarded_msg, 'video', None) or getattr(forwarded_msg, 'animation', None) or getattr(forwarded_msg, 'audio', None) or getattr(forwarded_msg, 'voice', None)):
                                        try:
                                            await callback.bot.edit_message_caption(chat_id=callback.from_user.id, message_id=forwarded_msg.message_id, caption='')
                                        except Exception:
                                            pass
                                        sent_via_forward = True
                                        try:
                                            if getattr(forwarded_msg, 'document', None):
                                                recent_sent_files[uid] = (forwarded_msg.document.file_unique_id, time.time())
                                            elif getattr(forwarded_msg, 'photo', None) and isinstance(forwarded_msg.photo, list) and forwarded_msg.photo:
                                                recent_sent_files[uid] = (forwarded_msg.photo[-1].file_unique_id, time.time())
                                            elif getattr(forwarded_msg, 'video', None):
                                                recent_sent_files[uid] = (forwarded_msg.video.file_unique_id, time.time())
                                        except Exception:
                                            pass
                                        await callback.answer()
                                        recent_sending[uid] = False
                                        return
                                except Exception as e:
                                    logger.info(f"forward_message по file_link не сработал: {e}")
                        except Exception as e:
                            logger.debug(f"Ошибка при попытке переслать файл по file_link: {e}")
            except Exception as e:
                logger.debug(f"Не удалось распарсить file_link для пересылки: {e}")
        # Если link был t.me: если пересылка прошла успешно — выходим.
        # Если пересылка не прошла — НЕ ДЕЛАЕМ fallback download/send (чтобы не присылать лишний файл),
        # а сообщаем об ошибке пользователю.
        if tried_tme:
            if sent_via_forward:
                try:
                    recent_sending[uid] = False
                except Exception:
                    pass
                return
            else:
                # Не удалось переслать файл из канала — сообщаем и выходим, без скачивания
                try:
                    # Не показываем модальный алерт пользователю, просто снимаем спиннер
                    await callback.answer()
                except Exception:
                    pass
                try:
                    recent_sending[uid] = False
                except Exception:
                    pass
                logger.info("t.me link attempted but no media forwarded — aborting without download to avoid duplicates")
                return

        # Убрана логика пересылки по post_link — пересылаем только файл по file_link (если t.me),
        # в противном случае продолжаем скачивание по file_link.

        # Сначала пробуем отправить файл по прямой ссылке (Telegram может сам скачать файл).
        # Это позволяет избежать создания временного `app_*` файла на сервере.
        try:
            try:
                if skip_send_by_url:
                    raise Exception("skip_send_by_url")
                # Если недавно был переслан тот же файл — пропускаем отправку по URL
                recent = recent_sent_files.get(uid)
                if recent and (time.time() - recent[1]) < 8:
                    logger.info(f"Skipping URL send: recent file sent to user {uid} {recent}")
                    await callback.answer()
                    recent_sending[uid] = False
                    return
                doc_msg = await callback.bot.send_document(callback.from_user.id, file_url)
                # Если файл, отправленный по URL, совпал с недавно пересланным, удалим дубль
                try:
                    fid = None
                    if getattr(doc_msg, 'document', None):
                        fid = doc_msg.document.file_unique_id
                    elif getattr(doc_msg, 'video', None):
                        fid = doc_msg.video.file_unique_id
                    if fid:
                        if recent_sent_files.get(callback.from_user.id, (None, 0))[0] == fid:
                            try:
                                await callback.bot.delete_message(chat_id=doc_msg.chat.id, message_id=doc_msg.message_id)
                            except Exception:
                                pass
                        else:
                            recent_sent_files[callback.from_user.id] = (fid, time.time())
                except Exception:
                    pass
                await callback.answer()
                return
            except Exception as e_url:
                logger.info(f"send_external_file: отправка по URL не удалась, перейдём к скачиванию: {e_url}")

            # Скачиваем файл во временный файл и отправляем (fallback)
            tmp_fd, tmp_path = None, None
            tmp_dir = os.path.join('files', 'tmp')
            os.makedirs(tmp_dir, exist_ok=True)
            import tempfile
            fd, tmp_path = tempfile.mkstemp(dir=tmp_dir, prefix=f"app_{app_id}_", suffix=os.path.splitext(file_url)[1] or '')
            os.close(fd)
            async with aiohttp.ClientSession() as session:
                async with session.get(file_url) as resp:
                    if resp.status != 200:
                        await callback.answer(f"❌ Не удалось скачать файл (HTTP {resp.status}).")
                        return
                    # Попытка извлечь имя файла из заголовка Content-Disposition
                    filename = None
                    try:
                        cd = resp.headers.get('content-disposition')
                        if cd:
                            import re
                            m = re.search(r"filename\*?=([^;]+)", cd)
                            if m:
                                fn = m.group(1).strip()
                                if fn.lower().startswith("utf-") or "'" in fn:
                                    parts = fn.split("''")
                                    if len(parts) > 1:
                                        fn = parts[-1]
                                filename = fn.strip('"')
                    except Exception:
                        filename = None

                    if not filename:
                        filename = os.path.basename(urlparse(file_url).path) or f"app_{app_id}{os.path.splitext(file_url)[1] or ''}"

                    with open(tmp_path, 'wb') as f:
                        while True:
                            chunk = await resp.content.read(1024 * 64)
                            if not chunk:
                                break
                            f.write(chunk)

            # Попытка отправки в ЛС из временного файла
            sent_to_pm = False
            try:
                doc_msg = await callback.bot.send_document(callback.from_user.id, FSInputFile(tmp_path, filename=filename))
                sent_to_pm = True
                # если этот файл совпадает с недавно пересланным — удалим дубль (новую отправку)
                try:
                    fid = None
                    if getattr(doc_msg, 'document', None):
                        fid = doc_msg.document.file_unique_id
                    elif getattr(doc_msg, 'video', None):
                        fid = doc_msg.video.file_unique_id
                    if fid and recent_sent_files.get(callback.from_user.id) == fid:
                        try:
                            await callback.bot.delete_message(chat_id=doc_msg.chat.id, message_id=doc_msg.message_id)
                        except Exception:
                            pass
                except Exception:
                    pass
            except Exception as e:
                logger.warning(f"Не удалось отправить внешний файл в ЛС: {e}")

            if not sent_to_pm:
                try:
                    ans_msg = await callback.message.answer_document(FSInputFile(tmp_path, filename=filename))
                    try:
                        fid = None
                        if isinstance(ans_msg, types.Message) and getattr(ans_msg, 'document', None):
                            fid = ans_msg.document.file_unique_id
                        if fid and recent_sent_files.get(callback.from_user.id, (None, 0))[0] == fid:
                            try:
                                await callback.bot.delete_message(chat_id=ans_msg.chat.id, message_id=ans_msg.message_id)
                            except Exception:
                                pass
                    except Exception:
                        pass
                except Exception as e2:
                    logger.error(f"Ошибка при fallback отправке внешнего файла: {e2}")
                    await callback.answer("❌ Не удалось отправить файл.")

        finally:
            # удаляем временный файл
            try:
                if tmp_path and os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass

        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в send_external_file: {e}")
        await callback.answer("❌ Произошла ошибка при отправке внешнего файла.")
    finally:
        try:
            recent_sending[uid] = False
        except Exception:
            pass

@dp.callback_query(F.data.startswith("already_participating:"))
async def already_participating(callback: types.CallbackQuery):
    """Пользователь уже участвует"""
    await callback.answer("✅ Вы уже участвуете в этом розыгрыше!", show_alert=True)

@dp.callback_query(F.data == "back_to_giveaways_user")
async def back_to_giveaways_user(callback: types.CallbackQuery):
    """Возврат к списку розыгрышей для пользователя"""
    await show_active_giveaways(callback.message)
    await callback.answer()

# ================== КАНАЛЫ ==================

@dp.message(F.text == "📢 Каналы")
async def channels_menu_handler(message: types.Message):
    """Обработчик кнопки каналов"""
    await message.answer(
        "📢 <b>Наши каналы и сообщества</b>\n\n"
        "Подписывайтесь на наши каналы, чтобы быть в курсе новостей, "
        "получать уведомления о новых играх и участвовать в эксклюзивных розыгрышах!",
        parse_mode='HTML',
        reply_markup=get_channels_menu()
    )

@dp.message(F.text == "📢 Наши каналы")
async def show_channels(message: types.Message):
    """Показать список каналов"""
    try:
        channels = db.channels
        
        if not channels:
            await message.answer(
                "📢 <b>Наши каналы</b>\n\n"
                "Список каналов пока пуст. Администраторы скоро добавят информацию.",
                parse_mode='HTML'
            )
            return
        # Отправляем отдельное сообщение для каждого канала с inline-кнопкой "Перейти"
        for i, channel in enumerate(channels, 1):
            title = channel.get('title', 'Без названия')
            link = channel.get('link', '#')
            description = channel.get('description', '')

            text = f"{i}. <b>{title}</b>"
            if description:
                text += f"\n{description}"

            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔗 Перейти", url=link)]
            ])

            await message.answer(text, parse_mode='HTML', reply_markup=kb)
    except Exception as e:
        logger.error(f"Ошибка в show_channels: {e}")
        await message.answer("❌ Произошла ошибка при загрузке каналов.")

# ================== ПРЕДЛОЖЕНИЯ ==================

@dp.message(F.text == "💡 Предложить игру")
async def suggest_menu_handler(message: types.Message):
    """Обработчик кнопки предложений"""
    await message.answer(
        "💡 <b>Предложить игру или идею</b>\n\n"
        "Вы можете предложить новую игру для добавления в наш каталог "
        "или поделиться идеей по улучшению GameHub.\n\n"
        "Выберите тип предложения:",
        parse_mode='HTML',
        reply_markup=get_suggestion_type_menu()
    )

@dp.callback_query(F.data == "suggest_idea")
async def suggest_idea_handler(callback: types.CallbackQuery, state: FSMContext):
    """Предложить идею"""
    await callback.message.answer(
        "💡 <b>Предложить идею</b>\n\n"
        "Пожалуйста, напишите вашу идею по улучшению GameHub или предложение "
        "по добавлению новых функций.\n\n"
        "Идея будет рассмотрена администраторами.\n\n"
        "<i>Отправьте вашу идею одним сообщением или нажмите 'Отмена' для выхода.</i>",
        parse_mode='HTML',
        reply_markup=get_cancel_button()
    )
    await state.set_state(IdeaSuggestionStates.wait_for_idea)
    await callback.answer()


@dp.callback_query(F.data.startswith("addapp_genre:"))
async def addapp_genre_callback(callback: types.CallbackQuery, state: FSMContext):
    # Установим жанр и переключимся на выбор размера (inline)
    _, genre = callback.data.split(":", 1)
    await state.update_data(genre=genre)
    await callback.message.edit_text(f"🎮 Жанр выбран: <b>{genre}</b>.\n\nВыберите размер:", parse_mode='HTML', reply_markup=build_size_inline_for_add())
    await state.set_state(AdminStates.add_app_size)
    await callback.answer()


@dp.callback_query(F.data == "addapp_genre_back")
async def addapp_genre_back(callback: types.CallbackQuery, state: FSMContext):
    # Возврат к вводу названия
    await callback.message.edit_text("📱 <b>Добавление нового приложения</b>\n\nВведите название приложения:", parse_mode='HTML', reply_markup=None)
    await state.set_state(AdminStates.add_app_name)
    await callback.answer()


@dp.callback_query(F.data.startswith("addapp_size:"))
async def addapp_size_callback(callback: types.CallbackQuery, state: FSMContext):
    _, size = callback.data.split(":", 1)
    await state.update_data(size_category=size)
    await callback.message.edit_text(f"📦 Размер выбран: <b>{size}</b>.\n\nВведите описание приложения:", parse_mode='HTML', reply_markup=build_inline_back("addapp_size_back"))
    await state.set_state(AdminStates.add_app_description)
    await callback.answer()


@dp.callback_query(F.data == "addapp_size_back")
async def addapp_size_back(callback: types.CallbackQuery, state: FSMContext):
    # Возврат к выбору жанра
    await callback.message.edit_text("🎮 Выберите жанр приложения:", reply_markup=build_genre_inline_for_add())
    await state.set_state(AdminStates.add_app_genre)
    await callback.answer()

@dp.message(IdeaSuggestionStates.wait_for_idea)
async def process_idea_suggestion(message: types.Message, state: FSMContext):
    """Обработчик идеи пользователя"""
    if message.text == "❌ Отмена":
        await message.answer("❌ Предложение идеи отменено.", reply_markup=get_main_menu(message.from_user.id))
        await state.clear()
        return
    
    if message.text == "🔙 В главное меню":
        await cmd_start(message)
        await state.clear()
        return
    
    # Сохраняем предложение
    suggestion_data = {
        'user_id': message.from_user.id,
        'username': message.from_user.username or '',
        'first_name': message.from_user.first_name or '',
        'type': 'idea',
        'content': message.text,
        'date': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'status': 'pending'
    }
    
    success = db.add_suggestion(suggestion_data)
    
    if success:
        await message.answer(
            "✅ <b>Спасибо за вашу идею!</b>\n\n"
            f"💡 <b>Ваша идея:</b>\n{message.text[:500]}...\n\n"
            "Ваше предложение будет рассмотрено администраторами.\n"
            "Мы ценим ваше участие в улучшении GameHub!",
            parse_mode='HTML',
            reply_markup=get_main_menu(message.from_user.id)
        )
    else:
        await message.answer(
            "❌ Произошла ошибка при сохранении идеи. Попробуйте позже.",
            reply_markup=get_main_menu(message.from_user.id)
        )
    
    await state.clear()

@dp.callback_query(F.data == "suggest_game")
async def suggest_game_handler(callback: types.CallbackQuery, state: FSMContext):
    """Предложить игру"""
    await callback.message.answer(
        "🎮 <b>Предложить игру</b>\n\n"
        "Пожалуйста, введите название игры или приложения:",
        parse_mode='HTML',
        reply_markup=get_cancel_button()
    )
    await state.set_state(SuggestionStates.suggest_game_name)
    await callback.answer()

@dp.message(SuggestionStates.suggest_game_name)
async def suggest_game_name_handler(message: types.Message, state: FSMContext):
    """Обработчик названия игры"""
    if message.text in ["❌ Отмена", "🔙 В главное меню"]:
        await message.answer("❌ Предложение игры отменено.", reply_markup=get_main_menu(message.from_user.id))
        await state.clear()
        return
    
    if len(message.text) > 100:
        await message.answer("❌ Название слишком длинное. Максимум 100 символов.")
        return
    
    await state.update_data(game_name=message.text)
    
    # Показываем клавиатуру с жанрами
    await message.answer(
        "🎮 Выберите жанр игры из списка:",
        reply_markup=get_genre_keyboard()
    )
    await state.set_state(SuggestionStates.suggest_game_genre)

@dp.message(SuggestionStates.suggest_game_genre)
async def suggest_game_genre_handler(message: types.Message, state: FSMContext):
    """Обработчик жанра игры"""
    if message.text == "🔙 Назад":
        await message.answer("Введите название игры:", reply_markup=get_cancel_button())
        await state.set_state(SuggestionStates.suggest_game_name)
        return
    
    if message.text not in Config.GENRES:
        await message.answer("❌ Пожалуйста, выберите жанр из предложенных.")
        return
    
    await state.update_data(game_genre=message.text)
    
    await message.answer(
        "🔗 Введите ссылку на игру (если есть) или напишите 'нет':",
        reply_markup=get_back_button()
    )
    await state.set_state(SuggestionStates.suggest_game_link)

@dp.message(SuggestionStates.suggest_game_link)
async def suggest_game_link_handler(message: types.Message, state: FSMContext):
    """Обработчик ссылки на игру"""
    if message.text == "🔙 Назад":
        await message.answer("Выберите жанр игры:", reply_markup=get_genre_keyboard())
        await state.set_state(SuggestionStates.suggest_game_genre)
        return
    
    data = await state.get_data()
    game_name = data.get('game_name', '')
    game_genre = data.get('game_genre', '')
    game_link = message.text if message.text.lower() != 'нет' else ''
    
    # Валидация ссылки если она есть
    if game_link and not validate_url(game_link):
        await message.answer("❌ Неверный формат ссылки. Пожалуйста, введите корректную ссылку или 'нет':")
        return
    
    # Сохраняем предложение
    suggestion_data = {
        'user_id': message.from_user.id,
        'username': message.from_user.username or '',
        'first_name': message.from_user.first_name or '',
        'type': 'game',
        'game_name': game_name,
        'game_genre': game_genre,
        'game_link': game_link,
        'date': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'status': 'pending'
    }
    
    success = db.add_suggestion(suggestion_data)
    
    if success:
        await message.answer(
            "✅ <b>Спасибо за предложение!</b>\n\n"
            f"🎮 <b>Игра:</b> {game_name}\n"
            f"🎮 <b>Жанр:</b> {game_genre}\n"
            f"🔗 <b>Ссылка:</b> {game_link if game_link else 'Не указана'}\n\n"
            "Ваше предложение будет рассмотрено администраторами. "
            "Если игра будет добавлена в каталог, вы получите уведомление.",
            parse_mode='HTML',
            reply_markup=get_main_menu(message.from_user.id)
        )
    else:
        await message.answer(
            "❌ Произошла ошибка при сохранении предложения. Попробуйте позже.",
            reply_markup=get_main_menu(message.from_user.id)
        )
    
    await state.clear()

# ================== ВАКАНСИИ ==================

@dp.message(F.text == "💼 Вакансии")
async def jobs_menu_handler(message: types.Message):
    """Обработчик кнопки вакансий"""
    await message.answer(
        "💼 <b>Вакансии в нашей команде</b>\n\n"
        "Мы всегда рады новым участникам команды! "
        "Выберите интересующую вас вакансию для получения подробной информации:",
        parse_mode='HTML',
        reply_markup=get_jobs_menu()
    )

@dp.callback_query(F.data.startswith("job_"))
async def job_details_handler(callback: types.CallbackQuery):
    """Детали вакансии"""
    job_type = callback.data.split("_")[1]
    
    jobs_info = {
        "poster": {
            "title": "👔 Работа постером",
            "description": (
                "<b>Обязанности:</b>\n"
                "• Поиск и публикация новых игр и приложений\n"
                "• Создание качественных описаний\n"
                "• Поддержание активности в каналах\n\n"
                "<b>Требования:</b>\n"
                "• Грамотная речь\n"
                "• Умение работать с графикой\n"
                "• Активность и ответственность\n\n"
                f"<b>Контакты:</b> {Config.POSTER_LINK}"
            )
        },
        "editor": {
            "title": "✏️ Работа редактором",
            "description": (
                "<b>Обязанности:</b>\n"
                "• Редактирование и проверка контента\n"
                "• Модерация предложений от пользователей\n"
                "• Контроль качества публикаций\n\n"
                "<b>Требования:</b>\n"
                "• Отличное знание русского языка\n"
                "• Внимательность к деталям\n"
                "• Опыт модерации или редактуры\n\n"
                f"<b>Контакты:</b> {Config.POSTER_LINK}"
            )
        },
        "moderator": {
            "title": "🛡️ Работа модератором",
            "description": (
                "<b>Обязанности:</b>\n"
                "• Модерация комментариев\n"
                "• Помощь пользователям\n"
                "• Поддержание порядка в чатах\n\n"
                "<b>Требования:</b>\n"
                "• Стрессоустойчивость\n"
                "• Коммуникабельность\n"
                "• Опыт модерации\n\n"
                f"<b>Контакты:</b> {Config.POSTER_LINK}"
            )
        }
    }
    
    if job_type not in jobs_info:
        await callback.answer("Вакансия не найдена")
        return
    
    job = jobs_info[job_type]
    
    await callback.message.answer(
        f"{job['title']}\n\n{job['description']}",
        parse_mode='HTML'
    )
    await callback.answer()

# ================== ПРИВАТНЫЙ ДОСТУП ==================

@dp.message((F.text == "🔒 Приватный доступ") | (F.text == "📬 Сообщения пользователей"))
async def private_access_or_pending_messages(message: types.Message):
    """Обработчик приватного доступа и сообщений пользователей для админов"""
    if message.text == "📬 Сообщения пользователей" and Config.is_admin(message.from_user.id):
        await cmd_pending_messages(message)
        return

    # Приватный доступ (старый функционал)
    text = (
        "🔒 <b>Приватный доступ</b>\n\n"
        "Получите доступ к эксклюзивному контенту, ранним релизам игр "
        "и специальным предложениям!\n\n"
        "Чтобы получить доступ, напишите менеджеру — нажмите кнопку ниже.\n\n"
        "<i>Менеджер поможет вам с доступом и отвечает в рабочее время.</i>"
    )
    buttons = []
    # Всегда показываем кнопку "Написать менеджеру" (через callback)
    buttons.append([InlineKeyboardButton(text='✉️ Написать менеджеру', callback_data='contact_owner')])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(text, parse_mode='HTML', reply_markup=kb)

# ================== ПОИСК ==================

@dp.message(F.text == "🔍 По названию")
async def search_by_name_start(message: types.Message, state: FSMContext):
    """Начало поиска по названию"""
    await message.answer(
        "🔍 <b>Поиск по названию</b>\n\n"
        "Введите название игры или приложения:",
        parse_mode='HTML',
        reply_markup=get_back_button()
    )
    await state.set_state(SearchStates.search_by_name)

@dp.message(SearchStates.search_by_name)
async def search_by_name_handler(message: types.Message, state: FSMContext):
    """Обработчик поиска по названию"""
    if message.text == "🔙 Назад":
        await search_menu_handler(message)
        await state.clear()
        return
    
    search_query = message.text.strip()
    if not search_query or len(search_query) < 2:
        await message.answer("❌ Введите минимум 2 символа для поиска.")
        return
    
    results = db.search_by_name(search_query)
    
    if not results:
        await message.answer(
            f"🔍 <b>Результаты поиска по запросу:</b> {search_query}\n\n"
            "😔 Ничего не найдено. Попробуйте другой запрос или проверьте правильность написания.",
            parse_mode='HTML',
            reply_markup=get_search_menu()
        )
    else:
        # Отправляем отдельное сообщение на каждое приложение (чтобы была клавиатура с файлом)
        await message.answer(f"🔍 <b>Найдено {len(results)} результатов по запросу '{search_query}':</b>", parse_mode='HTML')
        for app in results[:5]:
            text = (
                f"📱 <b>{app.get('name', 'Без названия')}</b>\n"
                f"🎮 <b>Жанр:</b> {app.get('genre', 'Не указан')}\n"
                f"📦 <b>Размер:</b> {app.get('size_category', 'Не указан')}\n\n"
                f"📝 {app.get('description', '')[:300]}\n"
            )
            keyboard = build_app_keyboard(app, app.get('id'))
            await message.answer(text, parse_mode='HTML', reply_markup=keyboard)

        # Навигация обратно
        await message.answer("Используйте меню для продолжения.", reply_markup=get_search_menu())
    
    await state.clear()

@dp.message(F.text == "🎮 По жанру")
async def search_by_genre_start(message: types.Message):
    """Начало поиска по жанру"""
    await message.answer(
        "🎮 <b>Поиск по жанру</b>\n\n"
        "Выберите жанр из списка:",
        parse_mode='HTML',
        reply_markup=get_genre_keyboard()
    )

@dp.message(F.text.in_(Config.GENRES))
async def search_by_genre_handler(message: types.Message, state: FSMContext):
    """Обработчик поиска по жанру — игнорирует ввод, если пользователь в FSM-состоянии."""
    current = await state.get_state()
    if current:
        return
    genre = message.text
    results = db.search_by_genre(genre)
    
    if not results:
        await message.answer(
            f"🎮 <b>Игры в жанре '{genre}':</b>\n\n"
            "😔 Пока нет игр в этом жанре. Следите за обновлениями!",
            parse_mode='HTML',
            reply_markup=get_search_menu()
        )
    else:
        await message.answer(f"🎮 <b>Найдено {len(results)} игр в жанре '{genre}':</b>", parse_mode='HTML')
        for app in results[:5]:
            text = (
                f"📱 <b>{app.get('name', 'Без названия')}</b>\n"
                f"📦 Размер: {app.get('size_category', 'Не указан')}\n"
                f"📝 {app.get('description', '')[:300]}\n"
            )
            keyboard = build_app_keyboard(app, app.get('id'))
            await message.answer(text, parse_mode='HTML', reply_markup=keyboard)

        await message.answer("Используйте меню для продолжения.", reply_markup=get_search_menu())

@dp.message(F.text == "📱 По размеру")
async def search_by_size_start(message: types.Message):
    """Начало поиска по размеру"""
    await message.answer(
        "📱 <b>Поиск по размеру</b>\n\n"
        "Выберите размер из списка:",
        parse_mode='HTML',
        reply_markup=get_size_keyboard()
    )

@dp.message(F.text.in_(Config.SIZES))
async def search_by_size_handler(message: types.Message, state: FSMContext):
    """Обработчик поиска по размеру — игнорирует ввод, если пользователь в FSM-состоянии."""
    current = await state.get_state()
    if current:
        return
    size = message.text
    results = db.search_by_size(size)
    
    if not results:
        await message.answer(
            f"📱 <b>Игры размером '{size}':</b>\n\n"
            "😔 Пока нет игр такого размера. Следите за обновлениями!",
            parse_mode='HTML',
            reply_markup=get_search_menu()
        )
    else:
        await message.answer(f"📱 <b>Найдено {len(results)} игр размером '{size}':</b>", parse_mode='HTML')
        for app in results[:5]:
            text = (
                f"📱 <b>{app.get('name', 'Без названия')}</b>\n"
                f"🎮 Жанр: {app.get('genre', 'Не указан')}\n"
                f"📝 {app.get('description', '')[:300]}\n"
            )
            keyboard = build_app_keyboard(app, app.get('id'))
            await message.answer(text, parse_mode='HTML', reply_markup=keyboard)

        await message.answer("Используйте меню для продолжения.", reply_markup=get_search_menu())

@dp.message(F.text == "📋 Все приложения")
async def show_all_apps(message: types.Message):
    """Показать все приложения с пагинацией"""
    try:
        page_data = db.get_apps_paginated(page=1, per_page=5)
        
        if not page_data['apps']:
            await message.answer(
                "📋 <b>Все приложения</b>\n\n"
                "😔 Пока нет приложений в базе. Администраторы скоро добавят контент!",
                parse_mode='HTML'
            )
            return
        
        # Создаем сообщение с первой страницей
        await send_apps_page(message, page_data)
    except Exception as e:
        logger.error(f"Ошибка в show_all_apps: {e}")
        await message.answer("❌ Произошла ошибка при загрузке приложений.")

async def send_apps_page(message: types.Message, page_data: Dict, edit_message: bool = False):
    """Отправить страницу с приложениями"""
    apps = page_data['apps']
    page = page_data['page']
    total_pages = page_data['total_pages']
    
    text = f"📋 <b>Все приложения</b> (Страница {page}/{total_pages})\n\n"
    
    for i, app in enumerate(apps, 1):
        text += (
            f"{i}. <b>{app.get('name', 'Без названия')}</b>\n"
            f"   🎮 Жанр: {app.get('genre', 'Не указан')}\n"
            f"   📦 Размер: {app.get('size_category', 'Не указан')}\n\n"
        )
    
    # Создаем клавиатуру пагинации
    builder = InlineKeyboardBuilder()
    
    if page > 1:
        builder.add(InlineKeyboardButton(text="◀️ Назад", callback_data=f"apps_page:{page-1}"))
    
    if page < total_pages:
        builder.add(InlineKeyboardButton(text="Вперед ▶️", callback_data=f"apps_page:{page+1}"))
    
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_search"))
    
    if edit_message and message.reply_markup:
        await message.edit_text(text, parse_mode='HTML', reply_markup=builder.as_markup())
    else:
        await message.answer(text, parse_mode='HTML', reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("apps_page:"))
async def apps_page_handler(callback: types.CallbackQuery):
    """Обработчик переключения страниц приложений"""
    try:
        page = int(callback.data.split(":")[1])
        page_data = db.get_apps_paginated(page=page, per_page=5)
        
        if page_data['apps']:
            await send_apps_page(callback.message, page_data, edit_message=True)
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в apps_page_handler: {e}")
        await callback.answer("❌ Ошибка при загрузке страницы.")

@dp.callback_query(F.data == "back_to_search")
async def back_to_search_handler(callback: types.CallbackQuery):
    """Возврат к меню поиска"""
    await search_menu_handler(callback.message)
    await callback.answer()

# ================== АДМИН-ПАНЕЛЬ ==================

# ================== 1. УПРАВЛЕНИЕ ПРИЛОЖЕНИЯМИ ==================

@dp.message(F.text == "➕ Добавить приложение")
async def add_app_start(message: types.Message, state: FSMContext):
    """Начало добавления приложения"""
    if not Config.is_editor(message.from_user.id):
        await message.answer("⛔ У вас нет прав для добавления приложений.")
        return
    
    await message.answer(
        "📱 <b>Добавление нового приложения</b>\n\n"
        "Введите название приложения:",
        parse_mode='HTML',
        reply_markup=get_cancel_button()
    )
    await state.set_state(AdminStates.add_app_name)


@dp.message(AdminStates.add_app_name)
async def add_app_name_handler(message: types.Message, state: FSMContext):
    """Обработчик названия приложения (первый шаг добавления)"""
    if message.text in ["❌ Отмена", "🔙 В главное меню"]:
        await admin_menu(message)
        await state.clear()
        return

    name = message.text.strip()
    if not name or len(name) < 2:
        await message.answer("❌ Название слишком короткое. Введите корректное название.")
        return

    await state.update_data(name=name)
    # Переходим к выбору жанра
    await message.answer(
        "🎮 Выберите жанр приложения:",
        reply_markup=build_genre_inline_for_add()
    )
    await state.set_state(AdminStates.add_app_genre)

@dp.message(AdminStates.add_manager_id)
async def manager_add_id_handler(message: types.Message, state: FSMContext):
    try:
        if message.text in ["❌ Отмена", "🔙 В главное меню"]:
            await admin_menu(message)
            await state.clear()
            return

        try:
            user_id = int(message.text.strip())
        except Exception:
            await message.answer("❌ Введите корректный числовой ID пользователя.")
            return

        admins = Config.load_admins()
        for admin in admins:
            if admin['id'] == user_id:
                await message.answer("❌ Этот пользователь уже администратор или менеджер.")
                await state.clear()
                return

        Config.add_admin(user_id, level=Config.ADMIN_LEVELS['manager'])
        await message.answer(f"✅ Пользователь {user_id} назначен менеджером.")
    except Exception as e:
        logger.exception(f"Unexpected error in manager_add_id_handler: {e}")
        try:
            await message.answer("❌ Внутренняя ошибка при назначении менеджера. Посмотрите логи.")
        except Exception:
            pass
    finally:
        try:
            await state.clear()
        except Exception:
            pass

@dp.message(AdminStates.add_app_genre)
async def add_app_genre_handler(message: types.Message, state: FSMContext):
    """Обработчик жанра приложения"""
    if message.text == "🔙 Назад":
        await message.answer("Введите название приложения:", reply_markup=get_cancel_button())
        await state.set_state(AdminStates.add_app_name)
        return
    
    if message.text not in Config.GENRES:
        await message.answer("❌ Пожалуйста, выберите жанр из предложенных.")
        return
    
    await state.update_data(genre=message.text)
    
    await message.answer(
        "📦 Выберите размер приложения:",
        reply_markup=build_size_inline_for_add()
    )
    await state.set_state(AdminStates.add_app_size)

@dp.message(AdminStates.add_app_size)
async def add_app_size_handler(message: types.Message, state: FSMContext):
    """Обработчик размера приложения"""
    if message.text == "🔙 Назад":
        await message.answer("Выберите жанр приложения:", reply_markup=get_genre_keyboard())
        await state.set_state(AdminStates.add_app_genre)
        return
    
    if message.text not in Config.SIZES:
        await message.answer("❌ Пожалуйста, выберите размер из предложенных.")
        return
    
    await state.update_data(size_category=message.text)
    
    await message.answer(
        "📝 Введите описание приложения:\n\n"
        "<i>Можно использовать HTML-разметку для форматирования</i>",
        parse_mode='HTML',
        reply_markup=get_back_button()
    )
    await state.set_state(AdminStates.add_app_description)

@dp.message(AdminStates.add_app_description)
async def add_app_description_handler(message: types.Message, state: FSMContext):
    """Обработчик описания приложения"""
    if message.text == "🔙 Назад":
        await message.answer("Выберите размер приложения:", reply_markup=get_size_keyboard())
        await state.set_state(AdminStates.add_app_size)
        return
    
    await state.update_data(description=message.text)
    
    await message.answer(
        "🔗 Введите ссылку на пост (если есть) или напишите 'нет':",
        reply_markup=get_back_button()
    )
    await state.set_state(AdminStates.add_app_post_link)

@dp.message(AdminStates.add_app_post_link)
async def add_app_post_link_handler(message: types.Message, state: FSMContext):
    """Обработчик ссылки на пост"""
    if message.text == "🔙 Назад":
        await message.answer("Введите описание приложения:", reply_markup=get_back_button())
        await state.set_state(AdminStates.add_app_description)
        return
    
    post_link = message.text if message.text.lower() != 'нет' else ''
    
    # Валидация ссылки если она есть
    if post_link and not validate_url(post_link):
        await message.answer("❌ Неверный формат ссылки. Пожалуйста, введите корректную ссылку или 'нет':")
        return
    # Сохраняем промежуточно данные и запрашиваем файл (ссылку или загрузку)
    await state.update_data(post_link=post_link)

    await message.answer(
        "📁 Прикрепите файл приложения (отправьте документ) или введите ссылку на файл.\n"
        "Если файла нет — введите 'нет'.",
        reply_markup=get_back_button()
    )
    await state.set_state(AdminStates.add_app_file_link)
@dp.message(AdminStates.add_app_file_link)
async def add_app_file_link_handler(message: types.Message, state: FSMContext):
    """Обработка файла или ссылки на файл при добавлении приложения"""
    # Отмена/назад
    if message.text in ["❌ Отмена", "🔙 В главное меню"]:
        await admin_menu(message)
        await state.clear()
        return

    if message.text == "🔙 Назад":
        await message.answer("Введите ссылку на пост (если есть) или напишите 'нет':", reply_markup=get_back_button())
        await state.set_state(AdminStates.add_app_post_link)
        return

    file_link = ''
    file_path = ''
    file_name = ''

    # Если прислан документ — сохраняем его
    if message.document:
        doc = message.document
        # Сохраняем в папку files с уникальным именем
        os.makedirs('files', exist_ok=True)
        safe_name = f"app_{int(datetime.now().timestamp())}_{doc.file_name or 'file'}"
        dest_path = os.path.join('files', safe_name)
        try:
            # Попробуем стандартный метод
            try:
                await message.document.download(destination_file=dest_path)
            except TypeError:
                # Некоторые версии используют другой парамет
                await message.document.download(custom_path=dest_path)
        except Exception as e:
            logger.warning(f"Первичная попытка скачивания не удалась: {e}")
            # Фallback: используем Bot API для получения файла
            try:
                file_obj = await message.bot.get_file(message.document.file_id)
                # Метод download_file может называться иначе; используем низкоуровневый метод
                await message.bot.download_file(file_obj.file_path, dest_path)
            except Exception as e2:
                logger.error(f"Ошибка сохранения документа (fallback): {e2}")
                await message.answer("❌ Не удалось сохранить файл. Попробуйте снова.")
                return

        file_path = dest_path
        file_name = os.path.basename(dest_path)

    else:
        # Текстовое поле: может быть 'нет' или ссылка
        if message.text.lower() == 'нет':
            file_link = ''
        elif validate_url(message.text):
            file_link = message.text
        else:
            # Может быть указан просто имя файла, сохраним как file_name (но файл может не существовать)
            file_name = message.text.strip()

    data = await state.get_data()
    # Составляем запись приложения
    app_data = {
        'name': data.get('name', ''),
        'genre': data.get('genre', ''),
        'size_category': data.get('size_category', ''),
        'description': data.get('description', ''),
        'post_link': data.get('post_link', ''),
        'file_link': file_link,
        'file_name': file_name,
        'file_path': file_path
    }

    success = db.add_app(app_data)

    if success:
        await message.answer(
            "✅ <b>Приложение успешно добавлено!</b>\n\n"
            f"📱 <b>Название:</b> {app_data['name']}\n"
            f"🎮 <b>Жанр:</b> {app_data['genre']}\n"
            f"📦 <b>Размер:</b> {app_data['size_category']}\n"
            f"🔗 <b>Ссылка:</b> {app_data['post_link'] if app_data['post_link'] else 'Не указана'}\n"
            f"📁 <b>Файл:</b> {app_data['file_name'] or (app_data['file_link'] or 'Не указан')}\n\n"
            f"<i>Приложение доступно для поиска пользователями.</i>",
            parse_mode='HTML',
            reply_markup=get_admin_menu(message.from_user.id)
        )
        # успешно добавлено приложение
    else:
        await message.answer(
            "❌ <b>Ошибка при добавлении приложения</b>\n\n"
            "Не удалось сохранить приложение в базу данных.",
            parse_mode='HTML',
            reply_markup=get_admin_menu(message.from_user.id)
        )

    await state.clear()

@dp.message(F.text == "✏️ Изменить приложение")
async def edit_app_start(message: types.Message):
    """Начало редактирования приложения"""
    if not Config.is_editor(message.from_user.id):
        await message.answer("⛔ У вас нет прав для редактирования приложений.")
        return
    
    apps = db.apps
    
    if not apps:
        await message.answer("📭 Нет приложений для редактирования.")
        return
    
    # Создаем клавиатуру с приложениями
    builder = InlineKeyboardBuilder()
    
    for app in apps[:10]:
        builder.add(InlineKeyboardButton(
            text=f"📱 {app.get('name', 'Без названия')[:30]}",
            callback_data=f"edit_app_select:{app.get('id')}"
        ))
    
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin"))
    
    await message.answer(
        "✏️ <b>Редактирование приложения</b>\n\n"
        "Выберите приложение для редактирования:",
        parse_mode='HTML',
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.startswith("edit_app_select:"))
async def edit_app_select_handler(callback: types.CallbackQuery, state: FSMContext):
    """Выбор приложения для редактирования"""
    try:
        app_id = int(callback.data.split(":")[1])
        app = db.get_app_by_id(app_id)
        
        if not app:
            await callback.answer("Приложение не найдено")
            return
        
        # Сохраняем ID приложения в состоянии
        await state.update_data(edit_app_id=app_id)
        
        # Создаем клавиатуру с полями для редактирования
        builder = InlineKeyboardBuilder()
        
        fields = [
            ("Название", "name"),
            ("Жанр", "genre"),
            ("Размер", "size_category"),
            ("Описание", "description"),
            ("Ссылка на пост", "post_link")
        ]
        
        for field_name, field_key in fields:
            builder.add(InlineKeyboardButton(
                text=f"✏️ {field_name}",
                callback_data=f"edit_app_field:{field_key}"
            ))
        
        builder.adjust(1)
        builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="edit_app_cancel"))
        
        await callback.message.edit_text(
            f"✏️ <b>Редактирование приложения</b>\n\n"
            f"📱 <b>Приложение:</b> {app.get('name', 'Без названия')}\n"
            f"🆔 <b>ID:</b> {app_id}\n\n"
            f"Выберите поле для редактирования:",
            parse_mode='HTML',
            reply_markup=builder.as_markup()
        )
        
        await state.set_state(AdminStates.edit_app_select)
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в edit_app_select_handler: {e}")
        await callback.answer("❌ Произошла ошибка")

@dp.callback_query(F.data.startswith("edit_app_field:"))
async def edit_app_field_handler(callback: types.CallbackQuery, state: FSMContext):
    """Выбор поля для редактирования"""
    try:
        field_key = callback.data.split(":")[1]
        
        await state.update_data(edit_field=field_key)
        
        field_names = {
            "name": "название",
            "genre": "жанр",
            "size_category": "размер",
            "description": "описание",
            "post_link": "ссылку на пост"
        }
        
        field_name = field_names.get(field_key, field_key)
        
        await callback.message.edit_text(
            f"✏️ <b>Редактирование приложения</b>\n\n"
            f"Введите новое значение для поля <b>{field_name}</b>:\n\n"
            f"<i>Для отмены нажмите кнопку ниже</i>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="edit_app_cancel")]]
            )
        )
        
        await state.set_state(AdminStates.edit_app_value)
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в edit_app_field_handler: {e}")
        await callback.answer("❌ Произошла ошибка")

@dp.message(AdminStates.edit_app_value)
async def edit_app_value_handler(message: types.Message, state: FSMContext):
    """Обработчик нового значения поля"""
    try:
        data = await state.get_data()
        app_id = data.get('edit_app_id')
        field_key = data.get('edit_field')
        
        if not app_id or not field_key:
            await message.answer("❌ Ошибка: данные не найдены.")
            await state.clear()
            return
        
        # Валидация в зависимости от поля
        if field_key == "genre" and message.text not in Config.GENRES:
            await message.answer("❌ Неверный жанр. Выберите из предложенных.")
            return
        
        if field_key == "size_category" and message.text not in Config.SIZES:
            await message.answer("❌ Неверный размер. Выберите из предложенных.")
            return
        
        if field_key == "post_link" and message.text.lower() != 'нет' and not validate_url(message.text):
            await message.answer("❌ Неверный формат ссылки.")
            return
        
        # Обновляем приложение
        success = db.update_app(app_id, field_key, message.text)
        
        if success:
            app = db.get_app_by_id(app_id)
            await message.answer(
                f"✅ <b>Приложение успешно обновлено!</b>\n\n"
                f"📱 <b>Приложение:</b> {app.get('name', 'Без названия')}\n"
                f"✏️ <b>Обновленное поле:</b> {field_key}\n"
                f"📝 <b>Новое значение:</b> {message.text}\n\n"
                f"<i>Изменения сохранены.</i>",
                parse_mode='HTML',
                reply_markup=get_admin_menu(message.from_user.id)
            )
        else:
            await message.answer(
                "❌ <b>Ошибка при обновлении приложения</b>\n\n"
                "Не удалось обновить приложение в базе данных.",
                parse_mode='HTML',
                reply_markup=get_admin_menu(message.from_user.id)
            )
        
        await state.clear()
    except Exception as e:
        logger.error(f"Ошибка в edit_app_value_handler: {e}")
        await message.answer("❌ Произошла ошибка при обновлении приложения.")
        await state.clear()

@dp.callback_query(F.data == "edit_app_cancel")
async def edit_app_cancel_handler(callback: types.CallbackQuery, state: FSMContext):
    """Отмена редактирования приложения"""
    await state.clear()
    await callback.message.edit_text("❌ Редактирование приложения отменено.")
    await callback.answer()

@dp.message(F.text == "🗑️ Удалить приложение")
async def delete_app_start(message: types.Message):
    """Начало удаления приложения"""
    if not Config.is_moderator(message.from_user.id):
        await message.answer("⛔ У вас нет прав для удаления приложений.")
        return
    
    apps = db.apps
    
    if not apps:
        await message.answer("📭 Нет приложений для удаления.")
        return
    
    # Создаем клавиатуру с приложениями
    builder = InlineKeyboardBuilder()
    
    for app in apps[:10]:
        builder.add(InlineKeyboardButton(
            text=f"🗑️ {app.get('name', 'Без названия')[:30]}",
            callback_data=f"delete_app_select:{app.get('id')}"
        ))
    
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin"))
    
    await message.answer(
        "🗑️ <b>Удаление приложения</b>\n\n"
        "Выберите приложение для удаления:",
        parse_mode='HTML',
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.startswith("delete_app_select:"))
async def delete_app_select_handler(callback: types.CallbackQuery):
    """Подтверждение удаления приложения"""
    try:
        app_id = int(callback.data.split(":")[1])
        app = db.get_app_by_id(app_id)
        
        if not app:
            await callback.answer("Приложение не найдено")
            return
        
        # Создаем клавиатуру подтверждения
        builder = InlineKeyboardBuilder()
        
        builder.add(InlineKeyboardButton(
            text="✅ Да, удалить",
            callback_data=f"delete_app_confirm:{app_id}"
        ))
        builder.add(InlineKeyboardButton(
            text="❌ Нет, отмена",
            callback_data="delete_app_cancel"
        ))
        
        builder.adjust(2)
        
        await callback.message.edit_text(
            f"🗑️ <b>Удаление приложения</b>\n\n"
            f"📱 <b>Приложение:</b> {app.get('name', 'Без названия')}\n"
            f"🎮 <b>Жанр:</b> {app.get('genre', 'Не указан')}\n"
            f"📦 <b>Размер:</b> {app.get('size_category', 'Не указан')}\n\n"
            f"<b>Вы уверены, что хотите удалить это приложение?</b>\n"
            f"<i>Это действие нельзя отменить.</i>",
            parse_mode='HTML',
            reply_markup=builder.as_markup()
        )
        
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в delete_app_select_handler: {e}")
        await callback.answer("❌ Произошла ошибка")

@dp.callback_query(F.data.startswith("delete_app_confirm:"))
async def delete_app_confirm_handler(callback: types.CallbackQuery):
    """Подтвержденное удаление приложения"""
    try:
        app_id = int(callback.data.split(":")[1])
        app = db.get_app_by_id(app_id)
        
        if not app:
            await callback.answer("Приложение не найдено")
            return
        
        app_name = app.get('name', 'Без названия')
        
        # Удаляем приложение
        success = db.delete_app(app_id)
        
        if success:
            await callback.message.edit_text(
                f"✅ <b>Приложение успешно удалено!</b>\n\n"
                f"📱 <b>Удаленное приложение:</b> {app_name}\n"
                f"🆔 <b>ID:</b> {app_id}\n\n"
                f"<i>Приложение больше не доступно для поиска.</i>",
                parse_mode='HTML'
            )
        else:
            await callback.message.edit_text(
                "❌ <b>Ошибка при удалении приложения</b>\n\n"
                "Не удалось удалить приложение из базы данных.",
                parse_mode='HTML'
            )
        
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в delete_app_confirm_handler: {e}")
        await callback.answer("❌ Произошла ошибка")

@dp.callback_query(F.data == "delete_app_cancel")
async def delete_app_cancel_handler(callback: types.CallbackQuery):
    """Отмена удаления приложения"""
    await callback.message.edit_text("❌ Удаление приложения отменено.")
    await callback.answer()

# ================== 2. УПРАВЛЕНИЕ КАНАЛАМИ ==================

@dp.message(F.text == "➕ Добавить канал")
async def add_channel_start(message: types.Message, state: FSMContext):
    """Начало добавления канала"""
    if not Config.is_moderator(message.from_user.id):
        await message.answer("⛔ У вас нет прав для добавления каналов.")
        return
    
    await message.answer(
        "📢 <b>Добавление нового канала</b>\n\n"
        "Введите название канала:",
        parse_mode='HTML',
        reply_markup=get_cancel_button()
    )
    await state.set_state(AdminStates.add_channel_title)

@dp.message(AdminStates.add_channel_title)
async def add_channel_title_handler(message: types.Message, state: FSMContext):
    """Обработчик названия канала"""
    if message.text in ["❌ Отмена", "🔙 В главное меню"]:
        await admin_menu(message)
        await state.clear()
        return
    
    if len(message.text) < 2:
        await message.answer("❌ Название слишком короткое. Минимум 2 символа.")
        return
    
    await state.update_data(title=message.text)
    
    await message.answer(
        "🔗 Введите ссылку на канал:",
        reply_markup=get_back_button()
    )
    await state.set_state(AdminStates.add_channel_link)

@dp.message(AdminStates.add_channel_link)
async def add_channel_link_handler(message: types.Message, state: FSMContext):
    """Обработчик ссылки на канал"""
    if message.text == "🔙 Назад":
        await message.answer("Введите название канала:", reply_markup=get_cancel_button())
        await state.set_state(AdminStates.add_channel_title)
        return
    
    if not validate_url(message.text):
        await message.answer("❌ Неверный формат ссылки. Пожалуйста, введите корректную ссылку.")
        return
    
    await state.update_data(link=message.text)
    # Сохраняем канал сразу после ссылки (без описания)
    data = await state.get_data()
    channel_data = {
        'title': data.get('title', ''),
        'link': data.get('link', message.text) or message.text,
        'description': '',
        'added_date': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    success = db.add_channel(channel_data)

    if success:
        await message.answer(
            "✅ <b>Канал успешно добавлен!</b>\n\n"
            f"📢 <b>Название:</b> {channel_data['title']}\n"
            f"🔗 <b>Ссылка:</b> {channel_data['link']}\n\n"
            f"<i>Канал теперь отображается в разделе 'Каналы'.</i>",
            parse_mode='HTML',
            reply_markup=get_admin_menu(message.from_user.id)
        )
    else:
        await message.answer(
            "❌ <b>Ошибка при добавлении канала</b>\n\n"
            "Не удалось сохранить канал в базу данных.",
            parse_mode='HTML',
            reply_markup=get_admin_menu(message.from_user.id)
        )

    await state.clear()



@dp.message(F.text == "🗑️ Удалить канал")
async def delete_channel_start(message: types.Message):
    """Начало удаления канала"""
    if not Config.is_moderator(message.from_user.id):
        await message.answer("⛔ У вас нет прав для удаления каналов.")
        return
    
    channels = db.channels
    
    if not channels:
        await message.answer("📭 Нет каналов для удаления.")
        return
    
    # Создаем клавиатуру с каналами
    builder = InlineKeyboardBuilder()
    
    for i, channel in enumerate(channels[:10]):
        builder.add(InlineKeyboardButton(
            text=f"🗑️ {channel.get('title', 'Без названия')[:30]}",
            callback_data=f"delete_channel_select:{i}"
        ))
    
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin"))
    
    await message.answer(
        "🗑️ <b>Удаление канала</b>\n\n"
        "Выберите канал для удаления:",
        parse_mode='HTML',
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.startswith("delete_channel_select:"))
async def delete_channel_select_handler(callback: types.CallbackQuery):
    """Подтверждение удаления канала"""
    try:
        channel_index = int(callback.data.split(":")[1])
        channels = db.channels
        
        if not 0 <= channel_index < len(channels):
            await callback.answer("Канал не найден")
            return
        
        channel = channels[channel_index]
        
        # Создаем клавиатуру подтверждения
        builder = InlineKeyboardBuilder()
        
        builder.add(InlineKeyboardButton(
            text="✅ Да, удалить",
            callback_data=f"delete_channel_confirm:{channel_index}"
        ))
        builder.add(InlineKeyboardButton(
            text="❌ Нет, отмена",
            callback_data="delete_channel_cancel"
        ))
        
        builder.adjust(2)
        
        await callback.message.edit_text(
            f"🗑️ <b>Удаление канала</b>\n\n"
            f"📢 <b>Канал:</b> {channel.get('title', 'Без названия')}\n"
            f"🔗 <b>Ссылка:</b> {channel.get('link', 'Не указана')}\n"
            f"📝 <b>Описание:</b> {channel.get('description', 'Нет описания')[:100]}...\n\n"
            f"<b>Вы уверены, что хотите удалить этот канал?</b>\n"
            f"<i>Это действие нельзя отменить.</i>",
            parse_mode='HTML',
            reply_markup=builder.as_markup()
        )
        
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в delete_channel_select_handler: {e}")
        await callback.answer("❌ Произошла ошибка")

@dp.callback_query(F.data.startswith("delete_channel_confirm:"))
async def delete_channel_confirm_handler(callback: types.CallbackQuery):
    """Подтвержденное удаление канала"""
    try:
        channel_index = int(callback.data.split(":")[1])
        channels = db.channels
        
        if not 0 <= channel_index < len(channels):
            await callback.answer("Канал не найден")
            return
        
        channel = channels[channel_index]
        channel_title = channel.get('title', 'Без названия')
        
        # Удаляем канал
        success = db.delete_channel(channel_index)
        
        if success:
            await callback.message.edit_text(
                f"✅ <b>Канал успешно удален!</b>\n\n"
                f"📢 <b>Удаленный канал:</b> {channel_title}\n\n"
                f"<i>Канал больше не отображается в разделе 'Каналы'.</i>",
                parse_mode='HTML'
            )
        else:
            await callback.message.edit_text(
                "❌ <b>Ошибка при удалении канала</b>\n\n"
                "Не удалось удалить канал из базы данных.",
                parse_mode='HTML'
            )
        
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в delete_channel_confirm_handler: {e}")
        await callback.answer("❌ Произошла ошибка")

@dp.callback_query(F.data == "delete_channel_cancel")
async def delete_channel_cancel_handler(callback: types.CallbackQuery):
    """Отмена удаления канала"""
    await callback.message.edit_text("❌ Удаление канала отменено.")
    await callback.answer()

# ================== РЕДАКТИРОВАНИЕ КАНАЛА ==================

@dp.message(F.text == "✏️ Изменить канал")
async def edit_channel_start(message: types.Message, state: FSMContext):
    """Начало редактирования канала"""
    if not Config.is_moderator(message.from_user.id):
        await message.answer("⛔ У вас нет прав для редактирования каналов.")
        return

    channels = db.channels
    if not channels:
        await message.answer("📭 Нет каналов для редактирования.")
        return

    builder = InlineKeyboardBuilder()
    for i, channel in enumerate(channels[:50]):
        builder.add(InlineKeyboardButton(
            text=f"✏️ {channel.get('title','Без названия')[:30]}",
            callback_data=f"edit_channel_select:{i}"
        ))

    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin"))

    await message.answer(
        "✏️ <b>Редактирование канала</b>\n\nВыберите канал для редактирования:",
        parse_mode='HTML',
        reply_markup=builder.as_markup()
    )


@dp.callback_query(F.data.startswith("edit_channel_select:"))
async def edit_channel_select(callback: types.CallbackQuery):
    try:
        idx = int(callback.data.split(":")[1])
        channels = db.channels
        if not 0 <= idx < len(channels):
            await callback.answer("Канал не найден")
            return

        ch = channels[idx]
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="Название", callback_data=f"edit_channel_field:{idx}:title"))
        builder.add(InlineKeyboardButton(text="Ссылка", callback_data=f"edit_channel_field:{idx}:link"))
        builder.add(InlineKeyboardButton(text="Описание", callback_data=f"edit_channel_field:{idx}:description"))
        builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin"))

        await callback.message.edit_text(
            f"✏️ <b>Редактирование канала</b>\n\n"
            f"📢 <b>Канал:</b> {ch.get('title','Без названия')}\n"
            f"🔗 <b>Ссылка:</b> {ch.get('link','Не указана')}\n"
            f"📝 <b>Описание:</b> {ch.get('description','Нет описания')}",
            parse_mode='HTML',
            reply_markup=builder.as_markup()
        )
        await callback.answer()
    except Exception as e:
        logger.exception(f"Ошибка в edit_channel_select: {e}")
        await callback.answer("❌ Произошла ошибка")


@dp.callback_query(F.data.startswith("edit_channel_field:"))
async def edit_channel_field(callback: types.CallbackQuery, state: FSMContext):
    try:
        _, idx_str, field = callback.data.split(":", 2)
        idx = int(idx_str)
    except Exception:
        await callback.answer("Ошибка данных", show_alert=True)
        return

    # Подготовим текст запроса в зависимости от поля
    if field == 'title':
        prompt = "Введите новое название канала:"
    elif field == 'link':
        prompt = "Введите новую ссылку на канал:"
    else:
        prompt = "Введите новое описание канала:"

    await state.update_data(edit_channel_index=idx, edit_channel_field=field)
    await callback.message.answer(prompt, reply_markup=get_cancel_button())
    await state.set_state(AdminStates.edit_channel_value)
    await callback.answer()


@dp.message(AdminStates.edit_channel_value)
async def edit_channel_value_handler(message: types.Message, state: FSMContext):
    if message.text in ["❌ Отмена", "🔙 В главное меню"]:
        await admin_menu(message)
        await state.clear()
        return

    data = await state.get_data()
    idx = data.get('edit_channel_index')
    field = data.get('edit_channel_field')

    if idx is None or field is None:
        await message.answer("❌ Нет данных для редактирования.")
        await state.clear()
        return

    # Валидация
    if field == 'link' and not validate_url(message.text):
        await message.answer("❌ Неверный формат ссылки. Попробуйте ещё раз.")
        return

    try:
        channels = db.channels
        if not 0 <= idx < len(channels):
            await message.answer("❌ Канал не найден.")
            await state.clear()
            return

        channels[idx][field] = message.text
        db.save_channels()

        await message.answer("✅ Поле канала обновлено.", reply_markup=get_admin_menu(message.from_user.id))
    except Exception as e:
        logger.exception(f"Ошибка при сохранении канала: {e}")
        await message.answer("❌ Не удалось сохранить изменения.")
    finally:
        await state.clear()

# ================== 3. УПРАВЛЕНИЕ РОЗЫГРЫШАМИ ==================

@dp.message(F.text == "🎁 Управление розыгрышами")
async def giveaways_management_start(message: types.Message):
    """Меню управления розыгрышами"""
    if not Config.is_full_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав для управления розыгрышами.")
        return
    
    await message.answer(
        "🎁 <b>Управление розыгрышами</b>\n\n"
        "Выберите действие:",
        parse_mode='HTML',
        reply_markup=get_giveaways_management_menu()
    )

@dp.callback_query(F.data == "giveaway_add")
async def giveaway_add_start(callback: types.CallbackQuery, state: FSMContext):
    """Начало создания розыгрыша"""
    if not Config.is_full_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет прав для создания розыгрышей.")
        return
    
    await callback.message.answer(
        "🎁 <b>Создание нового розыгрыша</b>\n\n"
        "Введите название розыгрыша:",
        parse_mode='HTML',
        reply_markup=get_cancel_button()
    )
    await state.set_state(AdminStates.add_giveaway_title)
    await callback.answer()

@dp.message(AdminStates.add_giveaway_title)
async def giveaway_add_title_handler(message: types.Message, state: FSMContext):
    """Обработчик названия розыгрыша"""
    if message.text in ["❌ Отмена", "🔙 В главное меню"]:
        await admin_menu(message)
        await state.clear()
        return
    
    if len(message.text) < 3:
        await message.answer("❌ Название слишком короткое. Минимум 3 символа.")
        return
    
    await state.update_data(title=message.text)
    
    await message.answer(
        "📝 Введите описание розыгрыша:",
        reply_markup=get_back_button()
    )
    await state.set_state(AdminStates.add_giveaway_description)

@dp.message(AdminStates.add_giveaway_description)
async def giveaway_add_description_handler(message: types.Message, state: FSMContext):
    """Обработчик описания розыгрыша"""
    if message.text == "🔙 Назад":
        await message.answer("Введите название розыгрыша:", reply_markup=get_cancel_button())
        await state.set_state(AdminStates.add_giveaway_title)
        return
    
    await state.update_data(description=message.text)
    
    await message.answer(
        "🏆 Введите приз розыгрыша:",
        reply_markup=get_back_button()
    )
    await state.set_state(AdminStates.add_giveaway_prize)

@dp.message(AdminStates.add_giveaway_prize)
async def giveaway_add_prize_handler(message: types.Message, state: FSMContext):
    """Обработчик приза розыгрыша"""
    if message.text == "🔙 Назад":
        await message.answer("Введите описание розыгрыша:", reply_markup=get_back_button())
        await state.set_state(AdminStates.add_giveaway_description)
        return
    
    await state.update_data(prize=message.text)
    
    await message.answer(
        "📅 Введите дату и время окончания розыгрыша (формат: ДД.ММ.ГГГГ ЧЧ:ММ):\n"
        "Например: 25.12.2024 20:00",
        reply_markup=get_back_button()
    )
    await state.set_state(AdminStates.add_giveaway_end_datetime)

@dp.message(AdminStates.add_giveaway_end_datetime)
async def giveaway_add_end_datetime_handler(message: types.Message, state: FSMContext):
    """Обработчик даты окончания розыгрыша"""
    if message.text == "🔙 Назад":
        await message.answer("Введите приз розыгрыша:", reply_markup=get_back_button())
        await state.set_state(AdminStates.add_giveaway_prize)
        return
    
    if not validate_datetime(message.text):
        await message.answer("❌ Неверный формат даты. Используйте формат: ДД.ММ.ГГГГ ЧЧ:ММ")
        return
    
    data = await state.get_data()
    
    # Проверяем, что дата в будущем
    try:
        end_datetime = datetime.strptime(message.text, "%d.%m.%Y %H:%M")
        if end_datetime <= datetime.now():
            await message.answer("❌ Дата окончания должна быть в будущем.")
            return
    except:
        await message.answer("❌ Ошибка при обработке даты.")
        return
    
    # Добавляем розыгрыш в базу
    giveaway_data = {
        'title': data.get('title', ''),
        'description': data.get('description', ''),
        'prize': data.get('prize', ''),
        'end_datetime': message.text,
        'created_by': message.from_user.id,
        'created_by_username': message.from_user.username or '',
        'created_by_name': message.from_user.first_name or ''
    }
    
    success = db.add_giveaway(giveaway_data)
    
    if success:
        await message.answer(
            "✅ <b>Розыгрыш успешно создан!</b>\n\n"
            f"🎁 <b>Название:</b> {giveaway_data['title']}\n"
            f"🏆 <b>Приз:</b> {giveaway_data['prize']}\n"
            f"📅 <b>Окончание:</b> {giveaway_data['end_datetime']}\n"
            f"📝 <b>Описание:</b> {giveaway_data['description'][:100]}...\n\n"
            f"<i>Розыгрыш теперь доступен для участия в разделе 'Розыгрыши'.</i>",
            parse_mode='HTML',
            reply_markup=get_admin_menu(message.from_user.id)
        )
        # Рассылка уведомления о новом розыгрыше всем зарегистрированным пользователям
        try:
            notify_text = (
                f"🎉 <b>Новый розыгрыш!</b>\n\n"
                f"🎁 <b>{giveaway_data.get('title')}</b>\n\n"
                f"📝 {giveaway_data.get('description', '')}\n\n"
                f"🏆 Приз: {giveaway_data.get('prize', '')}\n"
                f"📅 Окончание: {giveaway_data.get('end_datetime')}\n\n"
                f"Чтобы участвовать, откройте раздел 'Розыгрыши' в боте."
            )

            sent = 0
            failed = []
            for u in list(db.users):
                uid = u.get('id')
                try:
                    await message.bot.send_message(uid, notify_text, parse_mode='HTML')
                    sent += 1
                    await asyncio.sleep(0.05)
                except Exception as e:
                    logger.warning(f"Не удалось отправить уведомление пользователю {uid}: {e}")
                    failed.append(uid)

            logger.info(f"Рассылка нового розыгрыша: отправлено={sent}, не доставлено={len(failed)}")
        except Exception as e:
            logger.error(f"Ошибка при рассылке уведомлений о розыгрыше: {e}")
    else:
        await message.answer(
            "❌ <b>Ошибка при создании розыгрыша</b>\n\n"
            "Не удалось сохранить розыгрыш в базу данных.",
            parse_mode='HTML',
            reply_markup=get_admin_menu(message.from_user.id)
        )
    
    await state.clear()

@dp.callback_query(F.data == "giveaway_list")
async def giveaway_list_handler(callback: types.CallbackQuery):
    """Список розыгрышей для админов"""
    if not Config.is_full_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет прав для просмотра списка розыгрышей.")
        return
    
    giveaways = db.giveaways
    
    if not giveaways:
        await callback.message.answer("🎁 Нет созданных розыгрышей.")
        await callback.answer()
        return
    
    giveaways_text = "🎁 <b>Список розыгрышей:</b>\n\n"
    
    for i, giveaway in enumerate(giveaways[:10], 1):
        status = "🟢 Активен" if not giveaway.get('ended', False) else "🔴 Завершен"
        giveaways_text += (
            f"{i}. <b>{giveaway.get('title', 'Без названия')}</b>\n"
            f"   🆔 ID: {giveaway.get('id')}\n"
            f"   🏆 Приз: {giveaway.get('prize', 'Не указан')}\n"
            f"   📅 Окончание: {giveaway.get('end_datetime', 'Не указано')}\n"
            f"   👥 Участников: {len(giveaway.get('participants', []))}\n"
            f"   📊 Статус: {status}\n\n"
        )
    
    if len(giveaways) > 10:
        giveaways_text += f"<i>Показано 10 из {len(giveaways)} розыгрышей</i>"
    
    await callback.message.answer(giveaways_text, parse_mode='HTML')
    await callback.answer()


@dp.callback_query(F.data.startswith("giveaway_edit_select:"))
async def giveaway_edit_select(callback: types.CallbackQuery, state: FSMContext):
    if not Config.is_full_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет прав")
        return

    gid = int(callback.data.split(":")[1])
    giveaway = db.get_giveaway_by_id(gid)
    if not giveaway:
        await callback.answer("Розыгрыш не найден")
        return

    builder = InlineKeyboardBuilder()
    fields = [("Название","title"),("Описание","description"),("Приз","prize"),("Дата окончания","end_datetime")]
    for name, key in fields:
        builder.add(InlineKeyboardButton(text=f"✏️ {name}", callback_data=f"giveaway_edit_field:{gid}:{key}"))
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="giveaway_list"))

    await callback.message.edit_text(f"✏️ Редактирование: <b>{giveaway.get('title')}</b>", parse_mode='HTML', reply_markup=builder.as_markup())
    await state.update_data(edit_giveaway_id=gid)
    await callback.answer()


@dp.callback_query(F.data.startswith("giveaway_edit_field:"))
async def giveaway_edit_field(callback: types.CallbackQuery, state: FSMContext):
    if not Config.is_full_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет прав")
        return

    _, gid_str, field = callback.data.split(":",2)
    gid = int(gid_str)
    await state.update_data(edit_giveaway_id=gid, edit_giveaway_field=field)
    await callback.message.answer(f"Введите новое значение для поля <b>{field}</b>", parse_mode='HTML', reply_markup=get_back_button())
    await state.set_state(AdminStates.edit_giveaway_value)
    await callback.answer()


@dp.message(AdminStates.edit_giveaway_value)
async def giveaway_edit_value_handler(message: types.Message, state: FSMContext):
    data = await state.get_data()
    gid = data.get('edit_giveaway_id')
    field = data.get('edit_giveaway_field')

    if not gid or not field:
        await message.answer("❌ Ошибка: данные не найдены.")
        await state.clear()
        return

    # Валидация для даты
    if field == 'end_datetime' and not validate_datetime(message.text):
        await message.answer("❌ Неверный формат даты. Используйте: ДД.MM.ГГГГ ЧЧ:ММ")
        return

    success = db.update_giveaway(gid, field, message.text)
    if success:
        await message.answer("✅ Поле успешно обновлено.", reply_markup=get_admin_menu(message.from_user.id))
    else:
        await message.answer("❌ Не удалось обновить розыгрыш.", reply_markup=get_admin_menu(message.from_user.id))

    await state.clear()


@dp.callback_query(F.data.startswith("giveaway_delete_select:"))
async def giveaway_delete_select(callback: types.CallbackQuery):
    if not Config.is_full_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет прав")
        return

    gid = int(callback.data.split(":")[1])
    giveaway = db.get_giveaway_by_id(gid)
    if not giveaway:
        await callback.answer("Розыгрыш не найден")
        return

    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"giveaway_delete_confirm:{gid}"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="giveaway_list"))
    builder.adjust(2)

    await callback.message.edit_text(f"🗑️ Удалить розыгрыш: <b>{giveaway.get('title')}</b>?", parse_mode='HTML', reply_markup=builder.as_markup())
    await callback.answer()


@dp.callback_query(F.data.startswith("giveaway_delete_confirm:"))
async def giveaway_delete_confirm(callback: types.CallbackQuery):
    if not Config.is_full_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет прав")
        return

    gid = int(callback.data.split(":")[1])
    success = db.delete_giveaway(gid)
    if success:
        await callback.message.edit_text("✅ Розыгрыш удален.")
    else:
        await callback.message.edit_text("❌ Не удалось удалить розыгрыш.")
    await callback.answer()


@dp.callback_query(F.data.startswith("giveaway_end_select:"))
async def giveaway_end_select(callback: types.CallbackQuery):
    if not Config.is_full_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет прав")
        return

    gid = int(callback.data.split(":")[1])
    giveaway = db.get_giveaway_by_id(gid)
    if not giveaway:
        await callback.answer("Розыгрыш не найден")
        return

    participants = giveaway.get('participants', [])
    if not participants:
        # Просто отмечаем как завершенный
        db.end_giveaway(gid)
        await callback.message.edit_text("✅ Розыгрыш помечен как завершенный (нет участников).")
        await callback.answer()
        return

    # Предложим выбрать случайного победителя
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🎲 Выбрать случайного победителя", callback_data=f"giveaway_end_pick:{gid}"))
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data="giveaway_list"))
    builder.adjust(1)

    await callback.message.edit_text(f"🏁 Завершение розыгрыша: <b>{giveaway.get('title')}</b>\nУчастников: {len(participants)}", parse_mode='HTML', reply_markup=builder.as_markup())
    await callback.answer()


@dp.callback_query(F.data.startswith("giveaway_end_pick:"))
async def giveaway_end_pick(callback: types.CallbackQuery):
    if not Config.is_full_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет прав")
        return

    gid = int(callback.data.split(":")[1])
    giveaway = db.get_giveaway_by_id(gid)
    if not giveaway:
        await callback.answer("Розыгрыш не найден")
        return

    participants = giveaway.get('participants', [])
    if not participants:
        await callback.message.edit_text("❌ Нет участников для выбора победителя.")
        await callback.answer()
        return

    winner = random.choice(participants)
    db.end_giveaway(gid, winner_id=winner.get('id'), winner_username=winner.get('username'))

    await callback.message.edit_text(f"🏁 Розыгрыш <b>{giveaway.get('title')}</b> завершен!\n\n👑 Победитель: {winner.get('username') or winner.get('first_name')}\n🆔 ID: {winner.get('id')}", parse_mode='HTML')
    await callback.answer()

@dp.callback_query(F.data == "giveaway_edit")
async def giveaway_edit_start(callback: types.CallbackQuery):
    """Выбор розыгрыша для редактирования"""
    if not Config.is_full_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет прав для редактирования розыгрышей.")
        return

    giveaways = db.giveaways
    if not giveaways:
        await callback.message.answer("🎁 Нет созданных розыгрышей.")
        await callback.answer()
        return

    builder = InlineKeyboardBuilder()
    for g in giveaways[:20]:
        builder.add(InlineKeyboardButton(text=f"✏️ {g.get('title','Без названия')}", callback_data=f"giveaway_edit_select:{g.get('id')}"))
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin"))

    await callback.message.answer("✏️ <b>Редактирование розыгрыша</b>\n\nВыберите розыгрыш:", parse_mode='HTML', reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "giveaway_delete")
async def giveaway_delete_start(callback: types.CallbackQuery):
    """Выбор розыгрыша для удаления"""
    if not Config.is_full_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет прав для удаления розыгрышей.")
        return

    giveaways = db.giveaways
    if not giveaways:
        await callback.message.answer("🎁 Нет созданных розыгрышей.")
        await callback.answer()
        return

    builder = InlineKeyboardBuilder()
    for g in giveaways[:20]:
        builder.add(InlineKeyboardButton(text=f"🗑️ {g.get('title','Без названия')}", callback_data=f"giveaway_delete_select:{g.get('id')}"))
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin"))

    await callback.message.answer("🗑️ <b>Удаление розыгрыша</b>\n\nВыберите розыгрыш:", parse_mode='HTML', reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "giveaway_end")
async def giveaway_end_start(callback: types.CallbackQuery):
    """Выбор розыгрыша для завершения"""
    if not Config.is_full_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет прав для завершения розыгрышей.")
        return

    giveaways = db.get_active_giveaways()
    if not giveaways:
        await callback.message.answer("🎁 Нет активных розыгрышей для завершения.")
        await callback.answer()
        return

    builder = InlineKeyboardBuilder()
    for g in giveaways[:20]:
        builder.add(InlineKeyboardButton(text=f"🏁 {g.get('title','Без названия')}", callback_data=f"giveaway_end_select:{g.get('id')}"))
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin"))

    await callback.message.answer("🏁 <b>Завершение розыгрыша</b>\n\nВыберите розыгрыш для завершения:", parse_mode='HTML', reply_markup=builder.as_markup())
    await callback.answer()

# ================== 4. УПРАВЛЕНИЕ АДМИНИСТРАТОРАМИ ==================

@dp.message(F.text == "👥 Управление админами")
async def admin_management_start(message: types.Message):
    """Меню управления администраторами"""
    if not Config.is_owner(message.from_user.id):
        await message.answer("⛔ Только владелец может управлять администраторами.")
        return
    
    await message.answer(
        "👥 <b>Управление администраторами</b>\n\n"
        "Выберите действие:",
        parse_mode='HTML',
        reply_markup=get_admin_management_menu()
    )

@dp.callback_query(F.data == "admin_add")
async def admin_add_start_handler(callback: types.CallbackQuery, state: FSMContext):
    """Начало добавления администратора"""
    if not Config.is_owner(callback.from_user.id):
        await callback.answer("⛔ Только владелец может добавлять администраторов.")
        return
    
    await callback.message.answer(
        "👥 <b>Добавление администратора</b>\n\n"
        "Отправьте ID пользователя, которого хотите сделать администратором.\n\n"
        "<i>Как получить ID пользователя?\n"
        "1. Попросите пользователя отправить команду /id\n"
        "2. Или используйте бота @userinfobot для получения ID</i>",
        parse_mode='HTML',
        reply_markup=get_cancel_button()
    )
    await state.set_state(AdminStates.add_admin_id)
    await callback.answer()


@dp.callback_query(F.data == "admin_add_app")
async def admin_add_app_callback(callback: types.CallbackQuery, state: FSMContext):
    """Запуск добавления приложения из inline-меню админов"""
    # Проверим, что пользователь имеет права редактора
    if not Config.is_editor(callback.from_user.id):
        await callback.answer("⛔ У вас нет прав для добавления приложений.")
        return

    await callback.message.answer(
        "📱 <b>Добавление нового приложения</b>\n\nВведите название приложения:",
        parse_mode='HTML',
        reply_markup=get_cancel_button()
    )
    await state.set_state(AdminStates.add_app_name)
    await callback.answer()

@dp.message(AdminStates.add_admin_id)
async def admin_add_id_handler(message: types.Message, state: FSMContext):
    """Обработчик ID администратора"""
    try:
        if message.text in ["❌ Отмена", "🔙 В главное меню"]:
            await admin_menu(message)
            await state.clear()
            return

        try:
            user_id = int(message.text.strip())
        except ValueError:
            await message.answer("❌ Неверный формат ID. Введите числовой ID пользователя.")
            return

        # Проверяем, не пытаемся ли добавить самого себя или владельца
        if user_id == message.from_user.id:
            await message.answer("❌ Вы не можете добавить самого себя.")
            await state.clear()
            return

        if user_id == Config.DEFAULT_OWNER_ID:
            await message.answer("❌ Этот пользователь уже является владельцем.")
            await state.clear()
            return

        # Пробуем получить информацию о пользователе
        try:
            user = await message.bot.get_chat(user_id)
            username = user.username or ""
            first_name = user.first_name or ""

            # Создаем клавиатуру с уровнями доступа
            builder = InlineKeyboardBuilder()
            for level, role in Config.get_admin_roles().items():
                if level < 100:  # Не показываем владельца
                    # Сохраняем только user_id и level в callback_data (коротко),
                    # подробности получим в обработчике через get_chat
                    builder.add(InlineKeyboardButton(
                        text=role,
                        callback_data=f"admin_add_level:{user_id}:{level}"
                    ))

            builder.adjust(1)
            builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_add_cancel"))

            await message.answer(
                f"👥 <b>Добавление администратора</b>\n\n"
                f"Пользователь: {first_name} (@{username if username else 'нет'})\n"
                f"ID: <code>{user_id}</code>\n\n"
                f"Выберите уровень доступа для нового администратора:",
                parse_mode='HTML',
                reply_markup=builder.as_markup()
            )

        except Exception as e:
            logger.exception(f"Не удалось получить информацию о пользователе {user_id}")
            await message.answer(
                f"❌ Не удалось получить информацию о пользователе с ID {user_id}.\n"
                "Убедитесь, что пользователь начал диалог с ботом."
            )

        await state.clear()
    except Exception as e:
        logger.exception(f"Unexpected error in admin_add_id_handler: {e}")
        try:
            await message.answer("❌ Внутренняя ошибка при добавлении администратора. Посмотрите логи.")
        except Exception:
            pass
        await state.clear()

@dp.callback_query(F.data.startswith("admin_add_level:"))
async def admin_add_level_handler(callback: types.CallbackQuery):
    """Обработчик выбора уровня доступа"""
    if not Config.is_owner(callback.from_user.id):
        await callback.answer("⛔ Только владелец может добавлять администраторов.")
        return
    
    try:
        parts = callback.data.split(":")
        if len(parts) < 3:
            raise ValueError("Invalid callback data")
        user_id = int(parts[1])
        level = int(parts[2])

        # Получаем информацию о пользователе безопасно (может не начать диалог с ботом)
        try:
            user = await callback.bot.get_chat(user_id)
            username = user.username or ""
            first_name = user.first_name or ""
        except Exception:
            username = ""
            first_name = f"user_{user_id}"

        # Добавляем администратора
        success = Config.add_admin(user_id, username, first_name, level)
        
        if success:
            role_name = Config.get_role_name(level)
            await callback.message.edit_text(
                f"✅ <b>Администратор успешно добавлен!</b>\n\n"
                f"👤 <b>Пользователь:</b> {first_name} (@{username if username else 'нет'})\n"
                f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
                f"⚙️ <b>Роль:</b> {role_name}\n\n"
                f"Теперь пользователь имеет доступ к админ-панели с соответствующими правами.",
                parse_mode='HTML'
            )
        else:
            await callback.message.edit_text(
                "❌ <b>Не удалось добавить администратора</b>\n\n"
                "Возможные причины:\n"
                "• Пользователь уже является администратором\n"
                "• Произошла ошибка при сохранении",
                parse_mode='HTML'
            )
    except Exception as e:
        logger.error(f"Ошибка в admin_add_level_handler: {e}")
        await callback.message.edit_text("❌ Произошла ошибка при добавлении администратора.")
    
    await callback.answer()

@dp.callback_query(F.data == "admin_add_cancel")
async def admin_add_cancel_handler(callback: types.CallbackQuery):
    """Отмена добавления администратора"""
    await callback.message.edit_text("❌ Добавление администратора отменено.")
    await callback.answer()

@dp.callback_query(F.data == "admin_remove")
async def admin_remove_start(callback: types.CallbackQuery):
    """Начало удаления администратора"""
    if not Config.is_owner(callback.from_user.id):
        await callback.answer("⛔ Только владелец может удалять администраторов.")
        return
    
    admins = Config.load_admins()
    
    if len(admins) <= 1:  # Нельзя удалить всех админов
        await callback.answer("❌ Нельзя удалить всех администраторов.")
        return
    
    # Создаем клавиатуру с администраторами (кроме владельца)
    builder = InlineKeyboardBuilder()
    
    for admin in admins:
        if admin['id'] != Config.DEFAULT_OWNER_ID:  # Не показываем владельца
            role_name = Config.get_role_name(admin.get('level', 0))
            builder.add(InlineKeyboardButton(
                text=f"➖ {admin.get('first_name', 'Админ')} ({role_name})",
                callback_data=f"admin_remove_select:{admin['id']}"
            ))
    
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin_management"))
    
    await callback.message.edit_text(
        "👥 <b>Удаление администратора</b>\n\n"
        "Выберите администратора для удаления:",
        parse_mode='HTML',
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_remove_select:"))
async def admin_remove_select_handler(callback: types.CallbackQuery):
    """Подтверждение удаления администратора"""
    try:
        admin_id = int(callback.data.split(":")[1])
        admin_info = Config.get_admin_by_id(admin_id)
        
        if not admin_info:
            await callback.answer("Администратор не найден")
            return
        
        role_name = Config.get_role_name(admin_info.get('level', 0))
        
        # Создаем клавиатуру подтверждения
        builder = InlineKeyboardBuilder()
        
        builder.add(InlineKeyboardButton(
            text="✅ Да, удалить",
            callback_data=f"admin_remove_confirm:{admin_id}"
        ))
        builder.add(InlineKeyboardButton(
            text="❌ Нет, отмена",
            callback_data="admin_remove_cancel"
        ))
        
        builder.adjust(2)
        
        await callback.message.edit_text(
            f"👥 <b>Удаление администратора</b>\n\n"
            f"👤 <b>Администратор:</b> {admin_info.get('first_name', 'Админ')}\n"
            f"📱 <b>Username:</b> @{admin_info.get('username', 'нет')}\n"
            f"🆔 <b>ID:</b> <code>{admin_id}</code>\n"
            f"⚙️ <b>Роль:</b> {role_name}\n\n"
            f"<b>Вы уверены, что хотите удалить этого администратора?</b>\n"
            f"<i>Это действие нельзя отменить.</i>",
            parse_mode='HTML',
            reply_markup=builder.as_markup()
        )
        
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в admin_remove_select_handler: {e}")
        await callback.answer("❌ Произошла ошибка")

@dp.callback_query(F.data.startswith("admin_remove_confirm:"))
async def admin_remove_confirm_handler(callback: types.CallbackQuery):
    """Подтвержденное удаление администратора"""
    try:
        admin_id = int(callback.data.split(":")[1])
        
        # Удаляем администратора
        success = Config.remove_admin(admin_id)
        
        if success:
            await callback.message.edit_text(
                "✅ <b>Администратор успешно удален!</b>\n\n"
                f"🆔 <b>ID удаленного администратора:</b> <code>{admin_id}</code>\n\n"
                f"<i>Пользователь больше не имеет доступа к админ-панели.</i>",
                parse_mode='HTML'
            )
        else:
            await callback.message.edit_text(
                "❌ <b>Ошибка при удалении администратора</b>\n\n"
                "Не удалось удалить администратора.",
                parse_mode='HTML'
            )
        
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в admin_remove_confirm_handler: {e}")
        await callback.answer("❌ Произошла ошибка")

@dp.callback_query(F.data == "admin_remove_cancel")
async def admin_remove_cancel_handler(callback: types.CallbackQuery):
    """Отмена удаления администратора"""
    await callback.message.edit_text("❌ Удаление администратора отменено.")
    await callback.answer()

@dp.callback_query(F.data == "admin_change_level")
async def admin_change_level_start(callback: types.CallbackQuery):
    """Начало изменения уровня администратора"""
    if not Config.is_owner(callback.from_user.id):
        await callback.answer("⛔ Только владелец может изменять уровни доступа.")
        return
    
    admins = Config.load_admins()
    
    # Создаем клавиатуру с администраторами (кроме владельца)
    builder = InlineKeyboardBuilder()
    
    for admin in admins:
        if admin['id'] != Config.DEFAULT_OWNER_ID:  # Не показываем владельца
            role_name = Config.get_role_name(admin.get('level', 0))
            builder.add(InlineKeyboardButton(
                text=f"⚙️ {admin.get('first_name', 'Админ')} ({role_name})",
                callback_data=f"admin_change_select:{admin['id']}"
            ))
    
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin_management"))
    
    await callback.message.edit_text(
        "👥 <b>Изменение уровня доступа</b>\n\n"
        "Выберите администратора для изменения уровня:",
        parse_mode='HTML',
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_change_select:"))
async def admin_change_select_handler(callback: types.CallbackQuery):
    """Выбор нового уровня для администратора"""
    try:
        admin_id = int(callback.data.split(":")[1])
        admin_info = Config.get_admin_by_id(admin_id)
        
        if not admin_info:
            await callback.answer("Администратор не найден")
            return
        
        current_role = Config.get_role_name(admin_info.get('level', 0))
        
        # Создаем клавиатуру с уровнями доступа
        builder = InlineKeyboardBuilder()
        
        for level, role in Config.get_admin_roles().items():
            if level < 100:  # Не показываем владельца как опцию
                builder.add(InlineKeyboardButton(
                    text=role,
                    callback_data=f"admin_change_confirm:{admin_id}:{level}"
                ))
        
        builder.adjust(1)
        builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_change_cancel"))
        
        await callback.message.edit_text(
            f"👥 <b>Изменение уровня доступа</b>\n\n"
            f"👤 <b>Администратор:</b> {admin_info.get('first_name', 'Админ')}\n"
            f"📱 <b>Username:</b> @{admin_info.get('username', 'нет')}\n"
            f"⚙️ <b>Текущая роль:</b> {current_role}\n\n"
            f"Выберите новую роль для администратора:",
            parse_mode='HTML',
            reply_markup=builder.as_markup()
        )
        
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в admin_change_select_handler: {e}")
        await callback.answer("❌ Произошла ошибка")

@dp.callback_query(F.data.startswith("admin_change_confirm:"))
async def admin_change_confirm_handler(callback: types.CallbackQuery):
    """Подтверждение изменения уровня администратора"""
    try:
        _, admin_id_str, level_str = callback.data.split(":")
        admin_id = int(admin_id_str)
        new_level = int(level_str)
        
        admin_info = Config.get_admin_by_id(admin_id)
        
        if not admin_info:
            await callback.answer("Администратор не найден")
            return
        
        # Изменяем уровень администратора
        success = Config.update_admin_level(admin_id, new_level)
        
        if success:
            new_role = Config.get_role_name(new_level)
            old_role = Config.get_role_name(admin_info.get('level', 0))
            
            await callback.message.edit_text(
                f"✅ <b>Уровень доступа успешно изменен!</b>\n\n"
                f"👤 <b>Администратор:</b> {admin_info.get('first_name', 'Админ')}\n"
                f"📱 <b>Username:</b> @{admin_info.get('username', 'нет')}\n"
                f"🔄 <b>Изменение:</b> {old_role} → {new_role}\n\n"
                f"<i>Новый уровень доступа применен.</i>",
                parse_mode='HTML'
            )
        else:
            await callback.message.edit_text(
                "❌ <b>Ошибка при изменении уровня доступа</b>\n\n"
                "Не удалось изменить уровень администратора.",
                parse_mode='HTML'
            )
        
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в admin_change_confirm_handler: {e}")
        await callback.answer("❌ Произошла ошибка")

@dp.callback_query(F.data == "admin_change_cancel")
async def admin_change_cancel_handler(callback: types.CallbackQuery):
    """Отмена изменения уровня администратора"""
    await callback.message.edit_text("❌ Изменение уровня доступа отменено.")
    await callback.answer()

@dp.callback_query(F.data == "admin_list")
async def admin_list_handler(callback: types.CallbackQuery):
    """Список администраторов"""
    if not Config.is_owner(callback.from_user.id):
        await callback.answer("⛔ Только владелец может просматривать список администраторов.")
        return
    
    admins = Config.load_admins()
    
    if not admins:
        await callback.message.answer("👥 <b>Список администраторов пуст.</b>", parse_mode='HTML')
        await callback.answer()
        return
    
    admins_text = "👥 <b>Список администраторов GameHub:</b>\n\n"
    
    for i, admin in enumerate(admins, 1):
        role_name = Config.get_role_name(admin.get('level', 0))
        added_date = admin.get('added_date', 'Неизвестно')
        
        admins_text += (
            f"{i}. <b>{admin.get('first_name', 'Пользователь')}</b>\n"
            f"   👤 @{admin.get('username', 'нет')}\n"
            f"   🆔 <code>{admin.get('id')}</code>\n"
            f"   ⚙️ {role_name}\n"
            f"   📅 Добавлен: {added_date}\n\n"
        )
    
    await callback.message.answer(admins_text, parse_mode='HTML')
    await callback.answer()

@dp.callback_query(F.data == "back_to_admin_management")
async def back_to_admin_management_handler(callback: types.CallbackQuery):
    """Возврат к меню управления администраторами"""
    await admin_management_start(callback.message)
    await callback.answer()

# ================== СТАТИСТИКА И ПРЕДЛОЖЕНИЯ ==================

@dp.message(F.text == "📊 Статистика")
async def show_stats(message: types.Message):
    """Показать статистику"""
    if not Config.is_moderator(message.from_user.id):
        await message.answer("⛔ У вас нет доступа к статистике.")
        return
    
    try:
        stats = db.get_stats()
        admin_level = Config.get_admin_level(message.from_user.id)
        role_name = Config.get_role_name(admin_level)
        
        stats_text = (
            "📊 <b>Статистика GameHub</b>\n\n"
            f"👤 <b>Ваша роль:</b> {role_name}\n\n"
            f"📱 <b>Приложения:</b> {stats['apps_count']}\n"
            f"📢 <b>Каналы:</b> {stats['channels_count']}\n"
            f"💡 <b>Предложения всего:</b> {stats['suggestions_count']}\n"
            f"⏳ <b>Ожидают рассмотрения:</b> {stats['pending_suggestions']}\n"
            f"🎁 <b>Розыгрышей всего:</b> {stats['giveaways_count']}\n"
            f"🟢 <b>Активных:</b> {stats['active_giveaways']}\n"
            f"🔴 <b>Завершенных:</b> {stats['ended_giveaways']}\n\n"
            f"<i>Статистика обновляется в реальном времени</i>"
        )
        
        await message.answer(stats_text, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Ошибка в show_stats: {e}")
        await message.answer("❌ Произошла ошибка при загрузке статистики.")

@dp.message(F.text == "📝 Список предложений")
async def show_suggestions_list(message: types.Message):
    """Показать список предложений для админов"""
    if not Config.is_moderator(message.from_user.id):
        await message.answer("⛔ У вас нет доступа к предложениям.")
        return
    
    try:
        pending_suggestions = db.get_pending_suggestions()
        
        if not pending_suggestions:
            # Показываем пустой список предложений с кнопкой назад (архив в меню)
            builder = InlineKeyboardBuilder()
            builder.row(InlineKeyboardButton(text='🔙 Назад', callback_data='back_to_admin'))

            await message.answer(
                "📝 <b>Список предложений</b>\n\n"
                "Нет предложений, ожидающих рассмотрения.",
                parse_mode='HTML', reply_markup=builder.as_markup()
            )
            return
        
        # Показываем первое предложение с кнопками управления
        suggestion = pending_suggestions[0]
        await show_suggestion_with_controls(message, suggestion, 0, len(pending_suggestions))
        
    except Exception as e:
        logger.error(f"Ошибка в show_suggestions_list: {e}")
        await message.answer("❌ Произошла ошибка при загрузке предложений.")


@dp.message(F.text == "📂 Архив")
async def open_suggestion_archive(message: types.Message):
    """Открыть архив через reply-кнопку"""
    if not Config.is_moderator(message.from_user.id):
        await message.answer("⛔ У вас нет доступа к архиву.")
        return

    # Показываем архив как страницу (message вместо callback)
    await show_archive_page(message, page=1, status_filter='all')

async def show_suggestion_with_controls(message: types.Message, suggestion: Dict, index: int, total: int):
    """Показать предложение с кнопками управления"""
    suggestion_type = suggestion.get('type', 'идея')
    
    if suggestion_type == 'game':
        text = (
            f"📝 <b>Предложение игры</b> ({index + 1}/{total})\n\n"
            f"👤 <b>От:</b> {suggestion.get('first_name', 'Пользователь')} (@{suggestion.get('username', 'нет')})\n"
            f"🆔 <b>ID:</b> <code>{suggestion.get('user_id')}</code>\n"
            f"🎮 <b>Игра:</b> {suggestion.get('game_name', 'Не указано')}\n"
            f"🎮 <b>Жанр:</b> {suggestion.get('game_genre', 'Не указано')}\n"
            f"🔗 <b>Ссылка:</b> {suggestion.get('game_link', 'Не указана')}\n"
            f"📅 <b>Дата:</b> {suggestion.get('date', 'Неизвестно')}\n"
            f"🆔 <b>ID предложения:</b> <code>{suggestion.get('id')}</code>"
        )
    else:
        text = (
            f"📝 <b>Предложение идеи</b> ({index + 1}/{total})\n\n"
            f"👤 <b>От:</b> {suggestion.get('first_name', 'Пользователь')} (@{suggestion.get('username', 'нет')})\n"
            f"🆔 <b>ID:</b> <code>{suggestion.get('user_id')}</code>\n"
            f"💡 <b>Идея:</b>\n{suggestion.get('content', 'Нет содержания')[:500]}...\n"
            f"📅 <b>Дата:</b> {suggestion.get('date', 'Неизвестно')}\n"
            f"🆔 <b>ID предложения:</b> <code>{suggestion.get('id')}</code>"
        )
    
    # Создаем клавиатуру управления
    builder = InlineKeyboardBuilder()
    
    # Кнопки действий
    builder.add(InlineKeyboardButton(
        text="✅ Принять",
        callback_data=f"suggestion_approve:{suggestion.get('id')}:{index}"
    ))
    builder.add(InlineKeyboardButton(
        text="❌ Отклонить", 
        callback_data=f"suggestion_reject:{suggestion.get('id')}:{index}"
    ))
    
    
    # Кнопки навигации
    builder.adjust(2)
    
    if index > 0:
        builder.add(InlineKeyboardButton(
            text="◀️ Предыдущее",
            callback_data=f"suggestion_prev:{index}"
        ))
    
    if index < total - 1:
        builder.add(InlineKeyboardButton(
            text="Следующее ▶️",
            callback_data=f"suggestion_next:{index}"
        ))
    
    builder.adjust(2)
    # Кнопка назад
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_admin"))
    
    await message.answer(text, parse_mode='HTML', reply_markup=builder.as_markup())

@dp.callback_query(lambda c: c.data and any(c.data.startswith(p) for p in ("suggestion_approve:", "suggestion_reject:", "suggestion_prev:", "suggestion_next:")))
async def suggestion_action_handler(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик действий с предложениями"""
    if not Config.is_moderator(callback.from_user.id):
        await callback.answer("⛔ У вас нет прав для этой операции")
        return
    
    try:
        action, *params = callback.data.split(":")
        
        if action == "suggestion_approve":
            suggestion_id = int(params[0])
            index = int(params[1])
            # Найдём предложение до обновления
            suggestion = db.get_suggestion_by_id(suggestion_id)

            # Обновляем статус предложения
            db.update_suggestion_status(suggestion_id, "approved")

            await callback.answer("✅ Предложение принято!")

            # Попробуем уведомить автора
            try:
                user_id = suggestion.get('user_id')
                if user_id:
                    author_text = (
                        f"✅ Ваше предложение принято администратором {callback.from_user.first_name}!\n\n"
                        f"📌 Тип: {suggestion.get('type', 'идея')}\n"
                        f"🆔 ID предложения: {suggestion.get('id')}\n"
                        f"\nСпасибо за вклад — возможно, мы добавим вашу идею/игру в каталог."
                    )
                    await callback.bot.send_message(user_id, author_text, parse_mode='HTML')
            except Exception as e:
                logger.warning(f"Не удалось уведомить автора о принятии предложения {suggestion_id}: {e}")
            
            # Получаем обновленный список
            pending_suggestions = db.get_pending_suggestions()
            
            if pending_suggestions:
                if index >= len(pending_suggestions):
                    index = len(pending_suggestions) - 1
                await show_suggestion_with_controls(
                    callback.message, 
                    pending_suggestions[index], 
                    index, 
                    len(pending_suggestions)
                )
            else:
                await callback.message.edit_text(
                    "📝 <b>Список предложений</b>\n\n"
                    "Нет предложений, ожидающих рассмотрения.",
                    parse_mode='HTML'
                )
        
        elif action == "suggestion_reject":
            suggestion_id = int(params[0])
            index = int(params[1])
            # Сохраним данные в состоянии и переведём админа в режим ввода причины
            try:
                await state.update_data(suggestion_id=suggestion_id, index=index)
                await state.set_state(SuggestionStates.wait_for_reject_reason)
                await callback.message.answer(
                    "❌ <b>Причина отклонения</b>\n\nПожалуйста, введите причину отклонения для автора (или напишите 'без причины'):",
                    parse_mode='HTML',
                    reply_markup=get_cancel_button()
                )
            except Exception as e:
                logger.error(f"Ошибка при переходе в состояние ввода причины: {e}")
                await callback.answer("❌ Не удалось запросить причину отклонения")
                return
            await callback.answer()
        
        elif action == "suggestion_prev":
            index = int(params[0]) - 1
            pending_suggestions = db.get_pending_suggestions()
            
            if 0 <= index < len(pending_suggestions):
                await show_suggestion_with_controls(
                    callback.message,
                    pending_suggestions[index],
                    index,
                    len(pending_suggestions)
                )
            await callback.answer()
        
        elif action == "suggestion_next":
            index = int(params[0]) + 1
            pending_suggestions = db.get_pending_suggestions()
            
            if 0 <= index < len(pending_suggestions):
                await show_suggestion_with_controls(
                    callback.message,
                    pending_suggestions[index],
                    index,
                    len(pending_suggestions)
                )
            await callback.answer()
    
    except Exception as e:
        logger.error(f"Ошибка в suggestion_action_handler: {e}")
        await callback.answer("❌ Произошла ошибка")
    
@dp.callback_query(lambda c: c.data and c.data.startswith("suggestion_remove_archive:"))
async def suggestion_remove_archive_handler(callback: types.CallbackQuery):
    """Удаляет предложение из архива (перманентно). Поддерживает форматы:
    suggestion_remove_archive:<id>
    suggestion_remove_archive:<id>:<page>:<status>
    """
    parts = callback.data.split(":")
    try:
        suggestion_id = int(parts[1])
    except Exception:
        await callback.answer("Ошибка данных.", show_alert=True)
        return

    # По умолчанию возвращаемся на первую страницу и все статусы
    page = 1
    status = 'all'
    if len(parts) >= 4:
        try:
            page = int(parts[2])
            status = parts[3]
        except Exception:
            page = 1
            status = 'all'

    for i, s in enumerate(db.suggestions):
        if s.get('id') == suggestion_id:
            db.suggestions.pop(i)
            db.save_suggestions()
            await callback.answer("✅ Предложение удалено из архива.")
            try:
                await show_archive_page(callback, page=page, status_filter=status)
            except Exception:
                pass
            return
    await callback.answer("❌ Предложение не найдено.", show_alert=True)


@dp.message(SuggestionStates.wait_for_reject_reason)
async def suggestion_reject_reason_handler(message: types.Message, state: FSMContext):
    """Обработка ввода причины отклонения от администратора"""
    if message.text in ["❌ Отмена", "🔙 В главное меню"]:
        await message.answer("❌ Отклонение отменено.", reply_markup=get_admin_menu(message.from_user.id))
        await state.clear()
        return

    data = await state.get_data()
    suggestion_id = data.get('suggestion_id')
    index = data.get('index', 0)
    reason = message.text.strip() or 'без причины'

    if not suggestion_id:
        await message.answer("❌ Не найдено предложение для отклонения.")
        await state.clear()
        return

    # Сохраняем статус и причину
    try:
        db.set_suggestion_rejection(suggestion_id, reason)
    except Exception as e:
        logger.error(f"Ошибка при сохранении причины отклонения: {e}")
        await message.answer("❌ Не удалось сохранить причину отклонения.")
        await state.clear()
        return

    # Уведомляем автора
    try:
        suggestion = db.get_suggestion_by_id(suggestion_id)
        user_id = suggestion.get('user_id')
        if user_id:
            author_text = (
                f"❌ Ваше предложение было отклонено администратором {message.from_user.first_name}.\n\n"
                f"📌 Причина: {reason}\n"
                f"📌 Тип: {suggestion.get('type', 'идея')}\n"
                f"🆔 ID предложения: {suggestion.get('id')}\n\n"
                f"Если хотите — отправьте обновлённое предложение с учётом замечаний."
            )
            await message.bot.send_message(user_id, author_text, parse_mode='HTML')
    except Exception as e:
        logger.warning(f"Не удалось уведомить автора о причине отклонения {suggestion_id}: {e}")

    await message.answer("✅ Причина отклонения сохранена и автор уведомлён.", reply_markup=get_admin_menu(message.from_user.id))
    await state.clear()

    # Обновляем список ожидающих предложений
    try:
        await show_suggestions_list(message)
    except Exception:
        pass


@dp.callback_query(F.data == "suggestion_archive")
async def suggestion_archive_handler(callback: types.CallbackQuery):
    """Показать архив предложений с фильтром и пагинацией"""
    # Быстро отвечаем на callback, чтобы убрать спиннер у пользователя
    try:
        await callback.answer()
    except Exception:
        pass
    await show_archive_page(callback, page=1, status_filter='all')


async def show_archive_page(callback_or_message, page: int = 1, status_filter: str = 'all'):
    """Показ одной страницы архива. callback_or_message может быть CallbackQuery или Message"""
    try:
        # Лог для отладки: кто вызвал и сколько записей в БД
        try:
            caller = f"CallbackQuery from {callback_or_message.from_user.id}" if isinstance(callback_or_message, types.CallbackQuery) else f"Message from {callback_or_message.from_user.id}"
        except Exception:
            caller = "unknown caller"
        logger.info(f"show_archive_page called: caller={caller}, status_filter={status_filter}, total_db_suggestions={len(db.suggestions)}")
        # Получаем все архивные предложения (не pending)
        archived = [s for s in db.suggestions if s.get('status') != 'pending']

        # Применяем фильтр
        if status_filter in ('approved', 'rejected'):
            archived = [s for s in archived if s.get('status') == status_filter]

        # Если ничего не нашлось — в качестве fallback попробуем показать ВСЕ предложения
        if not archived:
            archived = db.suggestions.copy()
        logger.info(f"archived candidates count after filter/fallback = {len(archived)}; ids={[s.get('id') for s in archived]}")

        # Если и сейчас пусто — попробуем загрузить файл напрямую (вдруг db не инициализирован)
        if not archived:
            try:
                raw = Config.load_json_file(Config.SUGGESTIONS_FILE, [])
                if isinstance(raw, list):
                    archived = raw
            except Exception as e:
                logger.warning(f"Не удалось прочитать файл предложений напрямую: {e}")

        if not archived:
            target = callback_or_message.message if isinstance(callback_or_message, types.CallbackQuery) else callback_or_message
            # Показываем сообщение об отсутствии предложений, но даём фильтры и кнопку назад
            builder = InlineKeyboardBuilder()
            builder.row(
                InlineKeyboardButton(text='Все', callback_data=f'suggestion_archive_page:1:all'),
                InlineKeyboardButton(text='Принятые', callback_data=f'suggestion_archive_page:1:approved'),
                InlineKeyboardButton(text='Отклонённые', callback_data=f'suggestion_archive_page:1:rejected')
            )
            builder.row(InlineKeyboardButton(text='🔙 Назад', callback_data='back_to_admin'))

            await target.answer("📂 <b>Архив предложений</b>\n\nНет сохранённых предложений.", parse_mode='HTML', reply_markup=builder.as_markup())
            if isinstance(callback_or_message, types.CallbackQuery):
                await callback_or_message.answer()
            return

        per_page = 5
        total = len(archived)
        total_pages = (total + per_page - 1) // per_page
        page = max(1, min(page, total_pages))
        start = (page - 1) * per_page
        slice_items = archived[start:start + per_page]

        lines = [f"📂 <b>Архив предложений</b> — страница {page}/{total_pages}\n"]
        for i, s in enumerate(slice_items, start + 1):
            status = s.get('status', 'unknown')
            user = s.get('first_name') or s.get('username') or 'Пользователь'
            date = s.get('date', 'Неизвестно')
            sid = s.get('id')
            if s.get('type') == 'game':
                title = s.get('game_name', '—')
            else:
                title = (s.get('content','')[:50] + '...') if s.get('content') else '—'
            lines.append(f"{i}. <b>{title}</b> — {status} — {user} — {date} — ID:{sid}")

        text = "\n".join(lines)

        # Кнопки: для каждого элемента - Просмотр, и навигация + фильтры
        builder = InlineKeyboardBuilder()
        for s in slice_items:
            title = s.get('game_name') if s.get('type') == 'game' else (s.get('content','')[:30] + '...')
            builder.add(InlineKeyboardButton(text=f"📄 {title}", callback_data=f"suggestion_archive_view:{s.get('id')}:{page}:{status_filter}"))

        builder.adjust(1)
        # Навигация
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton(text='◀️ Назад', callback_data=f'suggestion_archive_page:{page-1}:{status_filter}'))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton(text='Далее ▶️', callback_data=f'suggestion_archive_page:{page+1}:{status_filter}'))
        if nav_buttons:
            builder.row(*nav_buttons)

        # Фильтры
        builder.row(
            InlineKeyboardButton(text='Все', callback_data=f'suggestion_archive_page:1:all'),
            InlineKeyboardButton(text='Принятые', callback_data=f'suggestion_archive_page:1:approved'),
            InlineKeyboardButton(text='Отклонённые', callback_data=f'suggestion_archive_page:1:rejected')
        )

        builder.row(InlineKeyboardButton(text='🔙 Назад', callback_data='back_to_admin'))

        target = callback_or_message.message if isinstance(callback_or_message, types.CallbackQuery) else callback_or_message
        if isinstance(callback_or_message, types.CallbackQuery):
            # Отправляем новое сообщение с содержимым архива (надежнее, чем edit_text)
            await callback_or_message.message.answer(text, parse_mode='HTML', reply_markup=builder.as_markup())
            await callback_or_message.answer()
        else:
            await target.answer(text, parse_mode='HTML', reply_markup=builder.as_markup())
    except Exception as e:
        logger.error(f"Ошибка в show_archive_page: {e}")
        if isinstance(callback_or_message, types.CallbackQuery):
            await callback_or_message.answer("❌ Произошла ошибка при получении архива")


@dp.callback_query(F.data.startswith('suggestion_archive_page:'))
async def suggestion_archive_page_handler(callback: types.CallbackQuery):
    try:
        _, page_str, status = callback.data.split(":")
        page = int(page_str)
        await show_archive_page(callback, page=page, status_filter=status)
    except Exception as e:
        logger.error(f"Ошибка в suggestion_archive_page_handler: {e}")
        await callback.answer("❌ Произошла ошибка")


@dp.callback_query(F.data == 'contact_owner')
async def contact_owner_callback(callback: types.CallbackQuery, state: FSMContext):
    """Callback при нажатии кнопки 'Написать владельцу' — переводим пользователя в состояние ввода сообщения."""
    try:
        await callback.answer()
    except Exception:
        pass

    await callback.message.answer(
        "✉️ Напишите сообщение менеджеру. Я перешлю его владельцу от вашего имени.\n\n"
        "Напишите текст сообщения и отправьте его.",
        reply_markup=get_cancel_button()
    )
    await state.set_state(ContactManagerStates.waiting_for_message)


@dp.message(ContactManagerStates.waiting_for_message)
async def contact_manager_message(message: types.Message, state: FSMContext):
    """Получаем сообщение от пользователя и пересылаем владельцу."""
    # Обработка отмены
    if message.text in ["❌ Отмена", "🔙 В главное меню"]:
        await message.answer("Отправка менеджеру отменена.", reply_markup=get_main_menu(message.from_user.id))
        await state.clear()
        return

    # Все сообщения сохраняем в архив (pending_messages.json)
    try:
        pending_path = 'data/pending_messages.json'
        pending = Config.load_json_file(pending_path, [])
        pending.append({
            'from_id': message.from_user.id,
            'username': message.from_user.username or '',
            'full_name': message.from_user.full_name,
            'text': message.text,
            'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        })
        Config.save_json_file(pending_path, pending)

        # Оповещение всех менеджеров (уровень >= manager)
        notify_text = (
            f"📩 Новое сообщение от пользователя {message.from_user.full_name} (id={message.from_user.id})\n"
            f"Username: @{message.from_user.username or 'не указан'}\n\n"
            f"Сообщение:\n{message.text}"
        )
        managers = [admin for admin in Config.load_admins() if admin.get('level', 0) >= Config.ADMIN_LEVELS['manager']]
        notified = False
        for manager in managers:
            try:
                await message.bot.send_message(manager['id'], notify_text)
                notified = True
            except Exception as e:
                logger.warning(f"Не удалось отправить менеджеру {manager['id']}: {e}")

        await message.answer("✅ Ваше сообщение отправлено менеджеру и сохранено в архиве сообщений.", reply_markup=get_main_menu(message.from_user.id))
    except Exception as e2:
        logger.error(f"Не удалось сохранить сообщение пользователя: {e2}")
        await message.answer("❌ Не удалось сохранить сообщение.")
    await state.clear()


@dp.callback_query(F.data.startswith('suggestion_archive_view:'))
async def suggestion_archive_view_handler(callback: types.CallbackQuery):
    # Сразу подтверждаем callback, чтобы убрать спиннер у пользователя
    try:
        await callback.answer()
    except Exception:
        pass

    logger.info(f"suggestion_archive_view_handler called: data={callback.data} from={getattr(callback.from_user, 'id', None)}")

    try:
        _, sid_str, page_str, status = callback.data.split(":")
        try:
            page = int(page_str)
        except Exception:
            page = 1
    except ValueError:
        # поддержка формата без page/status
        parts = callback.data.split(":")
        sid_str = parts[1]
        page_str = '1'
        status = 'all'
        page = 1

    try:
        # Быстро отвечаем на callback чтобы убрать спиннер
        try:
            await callback.answer()
        except Exception:
            pass

        sid = int(sid_str)
        suggestion = db.get_suggestion_by_id(sid)
        if not suggestion:
            await callback.answer("❌ Предложение не найдено")
            return

        # Формируем полную карточку
        if suggestion.get('type') == 'game':
            text = (
                f"📝 <b>Предложение игры</b>\n\n"
                f"👤 <b>От:</b> {suggestion.get('first_name','Пользователь')} (@{suggestion.get('username','нет')})\n"
                f"🆔 <b>ID:</b> <code>{suggestion.get('user_id')}</code>\n"
                f"🎮 <b>Игра:</b> {suggestion.get('game_name','Не указано')}\n"
                f"🎮 <b>Жанр:</b> {suggestion.get('game_genre','Не указано')}\n"
                f"🔗 <b>Ссылка:</b> {suggestion.get('game_link','Не указана')}\n"
                f"📅 <b>Дата:</b> {suggestion.get('date','Неизвестно')}\n"
                f"📌 <b>Статус:</b> {suggestion.get('status','unknown')}\n"
                f"🆔 <b>ID предложения:</b> <code>{suggestion.get('id')}</code>"
            )
        else:
            text = (
                f"📝 <b>Предложение идеи</b>\n\n"
                f"👤 <b>От:</b> {suggestion.get('first_name','Пользователь')} (@{suggestion.get('username','нет')})\n"
                f"🆔 <b>ID:</b> <code>{suggestion.get('user_id')}</code>\n"
                f"💡 <b>Идея:</b>\n{suggestion.get('content','Нет содержания')}\n"
                f"📅 <b>Дата:</b> {suggestion.get('date','Неизвестно')}\n"
                f"📌 <b>Статус:</b> {suggestion.get('status','unknown')}\n"
                f"🆔 <b>ID предложения:</b> <code>{suggestion.get('id')}</code>"
            )

        builder = InlineKeyboardBuilder()
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text='🔙 Назад в архив', callback_data=f'suggestion_archive_page:{page}:{status}'))
        # Кнопка удаления в самом просмотре архива
        builder.add(InlineKeyboardButton(text='🗑️ Удалить из архива', callback_data=f'suggestion_remove_archive:{sid}:{page}:{status}'))
        builder.row(InlineKeyboardButton(text='🔙 Назад', callback_data='back_to_admin'))

        # Редактируем сообщение архива, показывая карточку в том же сообщении
        try:
            await callback.message.edit_text(text, parse_mode='HTML', reply_markup=builder.as_markup())
            await callback.answer()
        except Exception:
            # если редактирование невозможно (например, устарело), отправляем новое сообщение
            await callback.message.answer(text, parse_mode='HTML', reply_markup=builder.as_markup())
            await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка в suggestion_archive_view_handler: {e}")
        await callback.answer("❌ Произошла ошибка при показе предложения")

# ================== КОМАНДА ДЛЯ ПОЛУЧЕНИЯ ID ==================

@dp.message(Command("id"))
async def cmd_id(message: types.Message):
    """Команда для получения своего ID"""
    user_id = message.from_user.id
    username = message.from_user.username or "не установлен"
    first_name = message.from_user.first_name or "Пользователь"
    
    text = (
        f"👤 <b>Ваши данные:</b>\n\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"👤 <b>Имя:</b> {first_name}\n"
        f"📱 <b>Username:</b> @{username}\n\n"
        f"<i>Этот ID может понадобиться администраторам для предоставления доступа.</i>"
    )
    
    await message.answer(text, parse_mode='HTML')


def load_pending_messages() -> List[Dict]:
    return Config.load_json_file('data/pending_messages.json', [])


def save_pending_messages(messages: List[Dict]):
    Config.save_json_file('data/pending_messages.json', messages)


async def show_pending_messages_list(message_or_callback):
    """Показать список сохранённых сообщений (для админов)."""
    try:
        if isinstance(message_or_callback, types.CallbackQuery):
            user_id = message_or_callback.from_user.id
        else:
            user_id = message_or_callback.from_user.id
    except Exception:
        user_id = None

    if not user_id or not Config.is_manager(user_id):
        if isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.answer("⛔ Только менеджер и выше может просматривать сообщения пользователей.")
        else:
            await message_or_callback.answer("⛔ Только менеджер и выше может просматривать сообщения пользователей.")
        return

    pending = load_pending_messages()

    if not pending:
        text = "📭 Нет сохранённых сообщений для менеджера."
        if isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.message.answer(text)
            await message_or_callback.answer()
        else:
            await message_or_callback.answer(text)
        return

    lines = ["📭 <b>Сохранённые сообщения</b>\n\n"]
    builder = InlineKeyboardBuilder()
    for i, p in enumerate(pending, start=1):
        preview = (p.get('text','')[:40] + '...') if p.get('text') else '«пустое сообщение»'
        lines.append(f"{i}. {p.get('full_name')} ({p.get('username') or '—'}) — {p.get('date')} — {preview}")
        builder.add(InlineKeyboardButton(text=f"✉️ {i}. {preview}", callback_data=f"pending_view:{i-1}"))

    builder.adjust(1)
    builder.row(InlineKeyboardButton(text='🔙 Назад', callback_data='back_to_admin'))

    text = "\n".join(lines)
    if isinstance(message_or_callback, types.CallbackQuery):
        await message_or_callback.message.answer(text, parse_mode='HTML', reply_markup=builder.as_markup())
        await message_or_callback.answer()
    else:
        await message_or_callback.answer(text, parse_mode='HTML', reply_markup=builder.as_markup())


@dp.message(Command("pending_messages"))
async def cmd_pending_messages(message: types.Message):
    """Команда для админов: показать сохранённые сообщения"""
    if not Config.is_manager(message.from_user.id):
        await message.answer("⛔ Только менеджер и выше может просматривать сообщения пользователей.")
        return
    await show_pending_messages_list(message)


@dp.callback_query(F.data.startswith('pending_view:'))
async def pending_view_handler(callback: types.CallbackQuery):
    try:
        await callback.answer()
    except Exception:
        pass
    if not Config.is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа")
        return

    try:
        _, idx_str = callback.data.split(":")
        idx = int(idx_str)
    except Exception:
        await callback.answer("❌ Неверный идентификатор сообщения")
        return

    pending = load_pending_messages()
    if idx < 0 or idx >= len(pending):
        await callback.answer("❌ Сообщение не найдено")
        return

    p = pending[idx]
    text = (
        f"📩 <b>Сообщение #{idx+1}</b>\n\n"
        f"От: {p.get('full_name')} (id={p.get('from_id')})\n"
        f"Username: @{p.get('username') or 'не указан'}\n"
        f"Дата: {p.get('date')}\n\n"
        f"Сообщение:\n{p.get('text')}"
    )

    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text='📨 Переслать менеджеру', callback_data=f'pending_forward:{idx}'))
    builder.add(InlineKeyboardButton(text='🗑️ Удалить', callback_data=f'pending_delete:{idx}'))
    builder.row(InlineKeyboardButton(text='🔙 Назад к списку', callback_data='pending_list_refresh'))

    try:
        await callback.message.answer(text, parse_mode='HTML', reply_markup=builder.as_markup())
        await callback.answer()
    except Exception:
        await callback.answer()


@dp.callback_query(F.data == 'pending_list_refresh')
async def pending_list_refresh(callback: types.CallbackQuery):
    if not Config.is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа")
        return
    await callback.answer()
    await show_pending_messages_list(callback)


@dp.callback_query(F.data.startswith('pending_forward:'))
async def pending_forward_handler(callback: types.CallbackQuery):
    if not Config.is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа")
        return
    try:
        await callback.answer()
    except Exception:
        pass

    try:
        _, idx_str = callback.data.split(":")
        idx = int(idx_str)
    except Exception:
        await callback.answer("❌ Неверный идентификатор")
        return

    pending = load_pending_messages()
    if idx < 0 or idx >= len(pending):
        await callback.answer("❌ Сообщение не найдено")
        return

    # Не удаляем сообщение из архива при пересылке — берём копию записи
    p = pending[idx]

    forward_text = (
        f"📩 Сообщение от {p.get('full_name')} (id={p.get('from_id')})\n"
        f"Username: @{p.get('username') or 'не указан'}\n\n"
        f"{p.get('text')}"
    )

    # Оповещение всех менеджеров (уровень >= manager)
    managers = [admin for admin in Config.load_admins() if admin.get('level', 0) >= Config.ADMIN_LEVELS['manager']]
    notified = False
    for manager in managers:
        try:
            await callback.bot.send_message(manager['id'], forward_text)
            notified = True
        except Exception as e:
            logger.warning(f"Не удалось переслать менеджеру {manager['id']}: {e}")
    if notified:
        await callback.message.answer("✅ Сообщение переслано менеджеру. (Сообщение остаётся в архиве)")
    else:
        await callback.message.answer("❌ Не удалось переслать сообщение менеджеру.")
    await callback.answer()


@dp.callback_query(F.data.startswith('pending_delete:'))
async def pending_delete_handler(callback: types.CallbackQuery):
    if not Config.is_admin(callback.from_user.id):
        await callback.answer("⛔ У вас нет доступа")
        return
    try:
        _, idx_str = callback.data.split(":")
        idx = int(idx_str)
    except Exception:
        await callback.answer("❌ Неверный идентификатор")
        return

    pending = load_pending_messages()
    if idx < 0 or idx >= len(pending):
        await callback.answer("❌ Сообщение не найдено")
        return

    p = pending.pop(idx)
    save_pending_messages(pending)
    await callback.answer("✅ Сообщение удалено")
    await show_pending_messages_list(callback)

# ================== ВСПОМОГАТЕЛЬНЫЕ ОБРАБОТЧИКИ ==================

@dp.callback_query(F.data == "back_to_admin")
async def back_to_admin_handler(callback: types.CallbackQuery):
    """Возврат в админ-панель"""
    user_id = callback.from_user.id
    # Проверяем доступ на основании пользователя, который нажал кнопку
    if not Config.is_admin(user_id):
        await callback.message.answer("⛔ У вас нет доступа к админ-панели.")
        await callback.answer()
        return

    admin_level = Config.get_admin_level(user_id)
    role_name = Config.get_role_name(admin_level)

    await callback.message.answer(
        f"⚙️ <b>Админ-панель GameHub</b>\n"
        f"👤 <b>Ваша роль:</b> {role_name}\n\n"
        f"Выберите действие:",
        parse_mode='HTML',
        reply_markup=get_admin_menu(user_id)
    )
    await callback.answer()

@dp.callback_query(F.data == "back_to_main")
async def back_to_main_handler(callback: types.CallbackQuery):
    """Возврат в главное меню"""
    await cmd_start(callback.message)
    await callback.answer()

# ================== ОБРАБОТКА НЕИЗВЕСТНЫХ КОМАНД ==================

@dp.message()
async def unknown_command(message: types.Message):
    """Обработка неизвестных команд"""
    # Регистрируем пользователя, чтобы он мог получать рассылки
    try:
        db.add_user(message.from_user.id, message.from_user.username or "", message.from_user.first_name or "")
    except Exception as e:
        logger.error(f"Не удалось добавить пользователя при unknown_command: {e}")
    await message.answer(
        "❓ <b>Неизвестная команда</b>\n\n"
        "Используйте меню ниже для навигации или команду /help для получения справки.",
        parse_mode='HTML',
        reply_markup=get_main_menu(message.from_user.id)
    )

# ================== ЗАПУСК БОТА ==================

async def main():
    """Основная функция запуска бота"""
    logger.info("Запуск бота GameHub...")
    
    # Проверяем наличие необходимых папок
    os.makedirs("data", exist_ok=True)
    os.makedirs("files", exist_ok=True)
    
    # Создаем дефолтные файлы если их нет
    if not os.path.exists(Config.ADMINS_FILE):
        logger.info("Создание файла администраторов...")
        Config.load_admins()
    
    logger.info("Бот GameHub запущен и готов к работе!")
    
    # Инициализируем Bot здесь, чтобы не требовать токен при импорте модуля
    token = Config.BOT_TOKEN
    # Попытка повторно прочитать токен из файла, если он не задан
    if not token and os.path.exists("bot_token.txt"):
        try:
            with open("bot_token.txt", "r", encoding='utf-8') as f:
                token = f.read().strip()
        except Exception:
            token = token

    if not token:
        logger.error("Не найден токен бота. Установите переменную окружения BOT_TOKEN или создайте файл bot_token.txt")
        return

    bot = Bot(token=token)
    async def _monitor_giveaways():
        """Фоновая задача: проверяет истёкшие розыгрыши и выбирает победителя."""
        while True:
            try:
                now = datetime.now()
                for giveaway in list(db.giveaways):
                    try:
                        gid = giveaway.get('id')
                        if not gid:
                            continue
                        # парсим дату окончания
                        end_str = giveaway.get('end_datetime', '')
                        if not end_str:
                            continue
                        try:
                            end_dt = datetime.strptime(end_str, "%d.%m.%Y %H:%M")
                        except Exception:
                            continue

                        # пропускаем если ещё не время
                        if now < end_dt:
                            continue

                        # Если розыгрыш уже помечен завершенным и есть победитель — пропускаем
                        if giveaway.get('ended') and giveaway.get('winner'):
                            continue

                        participants = giveaway.get('participants', []) or []

                        if not participants:
                            # помечаем как завершённый без победителя
                            db.end_giveaway(gid)
                            logger.info(f"Giveaway {gid} ended: no participants")
                            continue

                        # Выбираем случайного победителя
                        winner = random.choice(participants)
                        winner_id = winner.get('id')
                        winner_username = winner.get('username') or winner.get('first_name')

                        # Записываем победителя в базу
                        db.end_giveaway(gid, winner_id=winner_id, winner_username=winner_username)

                        # Отправляем личное сообщение победителю
                        try:
                            await bot.send_message(
                                winner_id,
                                f"🎉 Поздравляем! Вы выиграли в розыгрыше: <b>{giveaway.get('title')}</b>!\n\n" \
                                f"🆔 ID розыгрыша: {gid}\n\n" \
                                f"Свяжитесь с администрацией для получения приза.",
                                parse_mode='HTML'
                            )
                            logger.info(f"Notified winner {winner_id} for giveaway {gid}")
                        except Exception as e:
                            logger.error(f"Не удалось уведомить победителя {winner_id}: {e}")
                    except Exception as e:
                        logger.error(f"Error processing giveaway in monitor: {e}")
            except Exception as e:
                logger.error(f"Error in giveaway monitor loop: {e}")
            await asyncio.sleep(30)

    # Запускаем фоновую задачу контроля розыгрышей
    asyncio.create_task(_monitor_giveaways())
    try:
        await dp.start_polling(bot)
    finally:
        try:
            await bot.session.close()
        except Exception:
            pass

if __name__ == "__main__":
    asyncio.run(main())