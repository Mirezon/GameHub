
import os
import json
import tempfile
from typing import List, Dict, Optional
from datetime import datetime


class Config:
    @staticmethod
    def get_admin_ids() -> list:
        """Получить список id всех администраторов"""
        return [admin['id'] for admin in Config.load_admins()]
    # Загрузка токена из переменных окружения или файла
    BOT_TOKEN = os.environ.get("BOT_TOKEN") or ""

    # Если токен не задан, пробуем загрузить из файла (не выбрасываем ошибку при импорте)
    try:
        if not BOT_TOKEN and os.path.exists("bot_token.txt"):
            with open("bot_token.txt", "r", encoding='utf-8') as f:
                BOT_TOKEN = f.read().strip()
    except Exception:
        # Оставляем BOT_TOKEN пустым и проверяем при запуске
        BOT_TOKEN = BOT_TOKEN

    # Имена файлов базы данных
    CHANNELS_FILE = "data/channels.json"
    APPS_FILE = "data/apps.json"
    ADMINS_FILE = "data/admins.json"
    SUGGESTIONS_FILE = "data/suggestions.json"
    GIVEAWAYS_FILE = "data/giveaways.json"
    JOBS_FILE = "data/jobs.json"
    USERS_FILE = "data/users.json"

    # Создаем папку data если ее нет
    os.makedirs("data", exist_ok=True)
    os.makedirs("files", exist_ok=True)

    # ...остальной код класса без изменений...
    os.makedirs("files", exist_ok=True)
    
    # Ссылки на дополнительные ресурсы
    PRIVATE_LINK = "https://t.me/+YOUR_PRIVATE_CHANNEL_LINK"
    POSTER_LINK = "@Zx_x_delux"
    IDEA_FORM_LINK = "https://forms.gle/YOUR_FORM_LINK"
    # Имя менеджера (username без @) для кнопки "Написать менеджеру". Оставьте пустым, чтобы использовать OWNER ID.
    MANAGER_USERNAME = ""
    
    # Предопределенные значения для удобства
    GENRES = [
        "Игры", "Образование", "Социальные сети", "Фото/Видео",
        "Медицина", "Бизнес", "Путешествия", "Музыка",
        "Новости", "Спорт", "Утилиты", "Развлечения",
        "Продуктивность", "Шоппинг", "Финансы", "Другое"
    ]
    
    AGE_RATINGS = ["0+", "3+", "6+", "9+", "12+", "16+", "18+"]
    SIZES = ["<10 МБ", "10-50 МБ", "50-100 МБ", "100-500 МБ", "500+ МБ"]
    
    # Уровни доступа администраторов
    ADMIN_LEVELS = {
        "owner": 100,
        "manager": 90,
        "admin": 80,
        "moderator": 60,
        "editor": 40
    }
    @staticmethod
    def is_manager(user_id: int) -> bool:
        """Проверка, является ли пользователь менеджером или выше"""
        return Config.get_admin_level(user_id) >= Config.ADMIN_LEVELS['manager']
    
    # ID владельца по умолчанию (замените на свой)
    DEFAULT_OWNER_ID = 123456789  # ЗАМЕНИТЕ НА ВАШ ТЕЛЕГРАМ ID
    
    @staticmethod
    def load_json_file(filename: str, default_value) -> List[Dict]:
        """Безопасная загрузка JSON файла"""
        try:
            if os.path.exists(filename):
                with open(filename, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
        except (json.JSONDecodeError, Exception) as e:
            print(f"Ошибка загрузки {filename}: {e}")
        
        # Создаем файл с дефолтными значениями
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(default_value, f, ensure_ascii=False, indent=2)
        return default_value
    
    @staticmethod
    def save_json_file(filename: str, data) -> bool:
        """Безопасное сохранение в JSON файл"""
        try:
            # Создаем папку если ее нет
            dirpath = os.path.dirname(filename)
            if dirpath:
                os.makedirs(dirpath, exist_ok=True)

            # Записываем в временный файл и атомарно заменяем
            fd, tmp_path = tempfile.mkstemp(dir=dirpath or None, prefix="tmp", text=True)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as tf:
                    json.dump(data, tf, ensure_ascii=False, indent=2)
                os.replace(tmp_path, filename)
            finally:
                # Если временный файл остался, попробуем удалить
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
            return True
        except Exception as e:
            print(f"Ошибка сохранения {filename}: {e}")
            return False
    
    @staticmethod
    def load_admins() -> List[Dict]:
        """Загрузка списка администраторов"""
        default_admin = [{
            "id": Config.DEFAULT_OWNER_ID,
            "username": "owner",
            "first_name": "Владелец",
            "level": Config.ADMIN_LEVELS['owner'],
            "added_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }]
        
        admins = Config.load_json_file(Config.ADMINS_FILE, default_admin)
        
        # Добавляем поле level если его нет
        for admin in admins:
            if 'level' not in admin:
                admin['level'] = Config.ADMIN_LEVELS['owner'] if admin.get('id') == Config.DEFAULT_OWNER_ID else Config.ADMIN_LEVELS['moderator']
        
        return admins
    
    @staticmethod
    def _save_admins(admins: List[Dict]):
        """Сохранение списка администраторов"""
        Config.save_json_file(Config.ADMINS_FILE, admins)
    
    @staticmethod
    def is_admin(user_id: int) -> bool:
        """Проверка, является ли пользователь администратором любого уровня"""
        admins = Config.load_admins()
        return any(admin['id'] == user_id for admin in admins)
    
    @staticmethod
    def get_admin_level(user_id: int) -> int:
        """Получение уровня администратора"""
        admins = Config.load_admins()
        for admin in admins:
            if admin['id'] == user_id:
                return admin.get('level', 0)
        return 0
    
    @staticmethod
    def add_admin(user_id: int, username: str = "", first_name: str = "", level: int = None) -> bool:
        """Добавление администратора"""
        if user_id == Config.DEFAULT_OWNER_ID:
            return False  # Владелец уже есть
        
        admins = Config.load_admins()
        
        # Проверяем, нет ли уже такого админа
        for admin in admins:
            if admin['id'] == user_id:
                return False
        
        if level is None:
            level = Config.ADMIN_LEVELS['moderator']
        
        # Проверяем допустимый уровень
        valid_levels = list(Config.ADMIN_LEVELS.values())
        if level not in valid_levels:
            level = Config.ADMIN_LEVELS['moderator']
        
        admins.append({
            "id": user_id,
            "username": username or f"user_{user_id}",
            "first_name": first_name or "Пользователь",
            "level": level,
            "added_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        
        Config._save_admins(admins)
        return True
    
    @staticmethod
    def remove_admin(user_id: int) -> bool:
        """Удаление администратора (нельзя удалить владельца)"""
        if user_id == Config.DEFAULT_OWNER_ID:
            return False
        
        admins = Config.load_admins()
        initial_len = len(admins)
        admins = [admin for admin in admins if admin['id'] != user_id]
        
        if len(admins) < initial_len:
            Config._save_admins(admins)
            return True
        return False
    
    @staticmethod
    def update_admin_level(user_id: int, level: int) -> bool:
        """Обновление уровня администратора"""
        if user_id == Config.DEFAULT_OWNER_ID:
            return False  # Нельзя менять уровень владельцу
        
        valid_levels = list(Config.ADMIN_LEVELS.values())
        if level not in valid_levels:
            return False
        
        admins = Config.load_admins()
        for admin in admins:
            if admin['id'] == user_id:
                admin['level'] = level
                admin['modified_date'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                Config._save_admins(admins)
                return True
        return False
    
    @staticmethod
    def has_access(user_id: int, required_level: int) -> bool:
        """Проверка доступа пользователя к определенному уровню"""
        user_level = Config.get_admin_level(user_id)
        return user_level >= required_level
    
    @staticmethod
    def is_owner(user_id: int) -> bool:
        """Проверка, является ли пользователь владельцем"""
        return Config.get_admin_level(user_id) >= Config.ADMIN_LEVELS['owner']
    
    @staticmethod
    def is_full_admin(user_id: int) -> bool:
        """Проверка, является ли пользователь полным админом"""
        return Config.get_admin_level(user_id) >= Config.ADMIN_LEVELS['admin']
    
    @staticmethod
    def is_moderator(user_id: int) -> bool:
        """Проверка, является ли пользователь модератором или выше"""
        return Config.get_admin_level(user_id) >= Config.ADMIN_LEVELS['moderator']
    
    @staticmethod
    def is_editor(user_id: int) -> bool:
        """Проверка, является ли пользователь редактором или выше"""
        return Config.get_admin_level(user_id) >= Config.ADMIN_LEVELS['editor']
    
    @staticmethod
    def get_admin_roles() -> Dict[int, str]:
        """Получить словарь ролей администраторов"""
        return {
            100: "👑 Владелец",
            90: "🧑‍💼 Менеджер",
            80: "⚙️ Администратор",
            60: "🛡️ Модератор",
            40: "✏️ Редактор"
        }
    
    @staticmethod
    def get_role_name(level: int) -> str:
        """Получить название роли по уровню"""
        roles = Config.get_admin_roles()
        return roles.get(level, f"Уровень {level}")
    
    @staticmethod
    def get_admin_by_id(user_id: int) -> Optional[Dict]:
        """Получить информацию об администраторе по ID"""
        admins = Config.load_admins()
        for admin in admins:
            if admin['id'] == user_id:
                return admin
        return None