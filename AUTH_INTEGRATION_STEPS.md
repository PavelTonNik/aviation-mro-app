# ИНСТРУКЦИЯ ПО ИНТЕГРАЦИИ СИСТЕМЫ АУТЕНТИФИКАЦИИ

## ШАГ 1: Создайте таблицы в базе данных

```bash
python create_auth_tables.py
```

Это создаст:
- Таблицу `users` для пользователей
- Таблицу `notifications` для уведомлений
- Админа по умолчанию: **username: admin, password: admin123**

---

## ШАГ 2: Интегрируйте CSS в index.html

Откройте `frontend/index.html` и добавьте CSS **ПЕРЕД** закрывающим тегом `</style>`:

```html
/* === AUTHENTICATION STYLES === */
.login-modal {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(0, 0, 0, 0.7);
    display: flex;
    justify-content: center;
    align-items: center;
    z-index: 9999;
}

.login-box {
    background: white;
    padding: 40px;
    border-radius: 12px;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
    width: 400px;
    max-width: 90%;
}

.login-box h2 {
    text-align: center;
    margin-bottom: 30px;
    color: #333;
}

.login-error {
    background: #fee;
    color: #c33;
    padding: 10px;
    border-radius: 6px;
    margin-bottom: 15px;
    display: none;
}

/* User Header Bar */
.user-header {
    position: fixed;
    top: 0;
    right: 0;
    height: 60px;
    padding: 0 20px;
    display: flex;
    align-items: center;
    gap: 10px;
    z-index: 1000;
    background: rgba(255, 255, 255, 0.95);
    backdrop-filter: blur(10px);
    border-bottom: 1px solid rgba(0, 0, 0, 0.1);
}

.user-icon-btn {
    position: relative;
    width: 40px;
    height: 40px;
    border-radius: 50%;
    border: 2px solid #ddd;
    background: white;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.2s;
}

.user-icon-btn:hover {
    border-color: #007bff;
    transform: scale(1.05);
}

#user-profile-btn {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    font-weight: bold;
    font-size: 14px;
    border: none;
}

.notification-badge {
    position: absolute;
    top: -4px;
    right: -4px;
    min-width: 18px;
    height: 18px;
    background: #dc3545;
    color: white;
    border-radius: 3px;
    font-size: 11px;
    font-weight: bold;
    display: none;
    align-items: center;
    justify-content: center;
    padding: 0 4px;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
}

#add-user-btn {
    display: none;
    padding: 8px 16px;
    background: #28a745;
    color: white;
    border: none;
    border-radius: 6px;
    cursor: pointer;
    font-size: 14px;
    transition: background 0.2s;
}

#add-user-btn:hover {
    background: #218838;
}

/* Profile Dropdown */
.profile-dropdown {
    position: fixed;
    top: 65px;
    right: 20px;
    width: 280px;
    background: white;
    border-radius: 12px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
    display: none;
    z-index: 999;
}

.profile-dropdown.show {
    display: block;
    animation: dropdownSlide 0.2s ease;
}

@keyframes dropdownSlide {
    from {
        opacity: 0;
        transform: translateY(-10px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

.profile-header {
    padding: 20px;
    border-bottom: 1px solid #eee;
    text-align: center;
}

.profile-avatar {
    width: 60px;
    height: 60px;
    border-radius: 50%;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 24px;
    font-weight: bold;
    margin: 0 auto 10px;
}

.profile-name {
    font-size: 18px;
    font-weight: 600;
    margin-bottom: 4px;
}

.profile-position {
    font-size: 13px;
    color: #666;
    margin-bottom: 8px;
}

.profile-role {
    display: inline-block;
    padding: 4px 12px;
    background: #e3f2fd;
    color: #1976d2;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
}

.profile-menu {
    padding: 8px 0;
}

.profile-menu-item {
    padding: 12px 20px;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 12px;
    transition: background 0.2s;
}

.profile-menu-item:hover {
    background: #f8f9fa;
}

.profile-menu-item i {
    width: 20px;
    text-align: center;
    color: #666;
}

/* Notifications Panel */
.notifications-panel {
    position: fixed;
    top: 65px;
    right: 20px;
    width: 360px;
    max-height: 500px;
    background: white;
    border-radius: 12px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
    display: none;
    z-index: 999;
}

.notifications-panel.show {
    display: flex;
    flex-direction: column;
    animation: dropdownSlide 0.2s ease;
}

.notifications-header {
    padding: 16px 20px;
    border-bottom: 1px solid #eee;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.notifications-header h5 {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
}

.mark-all-read {
    color: #007bff;
    cursor: pointer;
    font-size: 13px;
    text-decoration: none;
}

.mark-all-read:hover {
    text-decoration: underline;
}

.notifications-list {
    overflow-y: auto;
    max-height: 440px;
}

.notification-item {
    padding: 16px 20px;
    border-bottom: 1px solid #f0f0f0;
    cursor: pointer;
    transition: background 0.2s;
}

.notification-item:hover {
    background: #f8f9fa;
}

.notification-item.unread {
    background: #f0f7ff;
}

.notification-item.unread:hover {
    background: #e3f2fd;
}

.notification-time {
    font-size: 12px;
    color: #999;
    margin-top: 6px;
}
```

---

## ШАГ 3: Добавьте HTML в index.html

Откройте `frontend/index.html` и добавьте **СРАЗУ ПОСЛЕ** открывающего тега `<body>`:

```html
<!-- Login Modal -->
<div id="login-modal" class="login-modal">
    <div class="login-box">
        <h2><i class="bi bi-shield-lock"></i> Aviation MRO Login</h2>
        <div id="login-error" class="login-error"></div>
        <form id="login-form">
            <div class="mb-3">
                <label class="form-label">Username</label>
                <input type="text" class="form-control" id="login-username" required autofocus>
            </div>
            <div class="mb-3">
                <label class="form-label">Password</label>
                <input type="password" class="form-control" id="login-password" required>
            </div>
            <button type="submit" class="btn btn-primary w-100">
                <i class="bi bi-box-arrow-in-right"></i> Sign In
            </button>
        </form>
        <div class="text-center mt-3">
            <small class="text-muted">Default: admin / admin123</small>
        </div>
    </div>
</div>

<!-- User Header -->
<div class="user-header">
    <button id="add-user-btn" title="Add User">
        <i class="bi bi-person-plus"></i> Add User
    </button>
    
    <button id="settings-btn" class="user-icon-btn" title="Settings">
        <i class="bi bi-gear"></i>
    </button>
    
    <button id="notifications-btn" class="user-icon-btn" title="Notifications">
        <i class="bi bi-bell"></i>
        <span id="notification-count" class="notification-badge">0</span>
    </button>
    
    <button id="user-profile-btn" class="user-icon-btn" title="Profile">
        <span id="user-initials">AA</span>
    </button>
</div>

<!-- Profile Dropdown -->
<div id="profile-dropdown" class="profile-dropdown">
    <div class="profile-header">
        <div class="profile-avatar" id="profile-avatar">AA</div>
        <div class="profile-name" id="profile-name">Admin User</div>
        <div class="profile-position" id="profile-position">System Administrator</div>
        <span class="profile-role" id="profile-role">admin</span>
    </div>
    <div class="profile-menu">
        <div class="profile-menu-item" onclick="editProfile()">
            <i class="bi bi-person"></i>
            <span>Edit Profile</span>
        </div>
        <div class="profile-menu-item" onclick="changePassword()">
            <i class="bi bi-key"></i>
            <span>Change Password</span>
        </div>
        <div class="profile-menu-item" onclick="logout()">
            <i class="bi bi-box-arrow-right"></i>
            <span>Logout</span>
        </div>
    </div>
</div>

<!-- Notifications Panel -->
<div id="notifications-panel" class="notifications-panel">
    <div class="notifications-header">
        <h5><i class="bi bi-bell"></i> Notifications</h5>
        <a href="#" class="mark-all-read" onclick="markAllNotificationsRead(); return false;">
            Mark all read
        </a>
    </div>
    <div id="notifications-list" class="notifications-list">
        <div class="text-center text-muted py-4">Loading...</div>
    </div>
</div>
```

---

## ШАГ 4: Добавьте JavaScript в index.html

Откройте `frontend/index.html` и добавьте **ПЕРЕД** закрывающим тегом `</body>`:

```html
<script src="auth_frontend.js"></script>
```

ИЛИ скопируйте весь код из `auth_frontend.js` и вставьте внутрь тега `<script>` в конец файла.

---

## ШАГ 5: Запустите приложение

```bash
python run_server.py
```

Откройте браузер: http://localhost:8000

---

## ТЕСТИРОВАНИЕ

1. **Войдите как админ:**
   - Username: `admin`
   - Password: `admin123`

2. **Проверьте функции:**
   - ✅ Иконка профиля появляется справа вверху
   - ✅ Колокольчик уведомлений с красным значком
   - ✅ Кнопка настроек (шестеренка)
   - ✅ Кнопка "Add User" (только для админа)

3. **Создайте нового пользователя:**
   - Нажмите "Add User"
   - Заполните форму
   - Выберите роль (Viewer, User, Admin)

4. **Проверьте уведомления:**
   - Выполните действия (создание, редактирование, удаление данных)
   - Уведомления появятся автоматически
   - Красная цифра покажет количество непрочитанных

---

## РОЛИ ПОЛЬЗОВАТЕЛЕЙ

### Admin (Администратор)
- ✅ Полный доступ ко всем функциям
- ✅ Создание/редактирование/удаление пользователей
- ✅ Просмотр всех уведомлений
- ✅ Управление всеми данными

### User (Пользователь)
- ✅ Создание/редактирование данных
- ✅ Просмотр своих уведомлений
- ❌ Не может управлять пользователями

### Viewer (Наблюдатель)
- ✅ Только просмотр данных
- ❌ Не может редактировать
- ❌ Не может удалять
- ❌ Не может управлять пользователями

---

## ДОПОЛНИТЕЛЬНЫЕ ФУНКЦИИ

### Смена пароля
1. Нажмите на иконку профиля
2. Выберите "Change Password"
3. Введите старый и новый пароль

### Выход из системы
1. Нажмите на иконку профиля
2. Выберите "Logout"

### Уведомления
- Автоматически обновляются каждые 30 секунд
- Красная цифра показывает количество непрочитанных
- Нажмите на уведомление, чтобы пометить как прочитанное
- "Mark all read" - пометить все как прочитанные

---

## TROUBLESHOOTING

**Проблема:** Не появляется окно логина
- Проверьте консоль браузера (F12)
- Убедитесь, что CSS добавлен правильно

**Проблема:** Ошибка при создании пользователя
- Проверьте, что таблицы созданы (`python create_auth_tables.py`)
- Проверьте, что сервер запущен

**Проблема:** Уведомления не работают
- Проверьте консоль браузера
- Убедитесь, что API endpoints работают: http://localhost:8000/api/notifications

---

## СЛЕДУЮЩИЕ ШАГИ

1. **Добавьте ограничения по ролям:**
   - Скройте кнопки Edit/Delete для роли Viewer
   - Добавьте проверки в JavaScript перед выполнением действий

2. **Добавьте загрузку фото профиля:**
   - Создайте endpoint для загрузки файлов
   - Измените `photo_url` в User модели

3. **Улучшите систему уведомлений:**
   - Добавьте WebSocket для real-time уведомлений
   - Добавьте звуковые оповещения

4. **Добавьте логи действий:**
   - Создайте таблицу audit_logs
   - Записывайте все действия пользователей
