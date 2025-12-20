# ИНСТРУКЦИЯ ПО ВНЕДРЕНИЮ СИСТЕМЫ АУТЕНТИФИКАЦИИ

## ✅ ЧТО СДЕЛАНО:

### 1. Backend (База данных и API):
- ✅ Добавлены таблицы: `users`, `notifications` в models.py
- ✅ Добавлены API endpoints в main.py:
  - POST /api/auth/login - вход в систему
  - GET /api/users - список пользователей
  - POST /api/users - создание пользователя
  - PUT /api/users/{id} - обновление пользователя
  - DELETE /api/users/{id} - удаление пользователя
  - GET /api/notifications - получить уведомления
  - GET /api/notifications/unread-count - количество непрочитанных
  - PUT /api/notifications/{id}/read - отметить прочитанным

### 2. Скрипты:
- ✅ create_auth_tables.py - создает таблицы и первого админа

## 📋 ЧТО НУЖНО ДОБАВИТЬ В FRONTEND (index.html):

### Добавьте эти CSS стили перед закрывающим тегом </style>:

```css
/* === USER PROFILE & NOTIFICATIONS === */
.user-header {
    display: flex;
    align-items: center;
    gap: 15px;
    padding: 10px 20px;
    background: white;
    border-bottom: 1px solid #e0e0e0;
    position: fixed;
    top: 0;
    right: 0;
    left: 260px;
    z-index: 1000;
    transition: left 0.3s;
}

#wrapper.toggled .user-header {
    left: 0;
}

.user-icon-group {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 15px;
}

.user-icon-btn {
    position: relative;
    background: none;
    border: none;
    cursor: pointer;
    padding: 8px;
    border-radius: 50%;
    transition: background 0.2s;
}

.user-icon-btn:hover {
    background: #f0f0f0;
}

.user-icon-btn i {
    font-size: 20px;
    color: #333;
}

.notification-badge {
    position: absolute;
    top: 3px;
    right: 3px;
    background: #dc3545;
    color: white;
    border-radius: 3px;
    padding: 2px 6px;
    font-size: 11px;
    font-weight: bold;
    min-width: 18px;
    text-align: center;
}

.user-avatar {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    background: #007bff;
    color: white;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: bold;
    cursor: pointer;
    font-size: 14px;
}

.user-avatar img {
    width: 100%;
    height: 100%;
    border-radius: 50%;
    object-fit: cover;
}

/* Profile Dropdown */
.profile-dropdown {
    position: absolute;
    top: 55px;
    right: 20px;
    background: white;
    border-radius: 8px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    min-width: 280px;
    display: none;
    z-index: 1001;
}

.profile-dropdown.show {
    display: block;
}

.profile-header {
    padding: 20px;
    border-bottom: 1px solid #e0e0e0;
    text-align: center;
}

.profile-header img, .profile-header .avatar-placeholder {
    width: 60px;
    height: 60px;
    border-radius: 50%;
    margin-bottom: 10px;
}

.avatar-placeholder {
    background: #007bff;
    color: white;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 24px;
    font-weight: bold;
}

.profile-dropdown-item {
    padding: 12px 20px;
    cursor: pointer;
    transition: background 0.2s;
    display: flex;
    align-items: center;
    gap: 10px;
}

.profile-dropdown-item:hover {
    background: #f8f9fa;
}

.profile-dropdown-item i {
    width: 20px;
}

/* Notifications Panel */
.notifications-panel {
    position: absolute;
    top: 55px;
    right: 80px;
    background: white;
    border-radius: 8px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    width: 360px;
    max-height: 500px;
    display: none;
    z-index: 1001;
}

.notifications-panel.show {
    display: block;
}

.notifications-header {
    padding: 15px 20px;
    border-bottom: 1px solid #e0e0e0;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.notifications-list {
    max-height: 400px;
    overflow-y: auto;
}

.notification-item {
    padding: 15px 20px;
    border-bottom: 1px solid #f0f0f0;
    cursor: pointer;
    transition: background 0.2s;
}

.notification-item:hover {
    background: #f8f9fa;
}

.notification-item.unread {
    background: #e3f2fd;
}

.notification-item.unread:hover {
    background: #bbdefb;
}

.notification-time {
    font-size: 11px;
    color: #999;
    margin-top: 5px;
}

/* Login Modal */
.login-modal {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(0,0,0,0.7);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 9999;
}

.login-box {
    background: white;
    border-radius: 12px;
    padding: 40px;
    width: 400px;
    box-shadow: 0 10px 40px rgba(0,0,0,0.3);
}

.login-logo {
    text-align: center;
    margin-bottom: 30px;
}

.login-logo h2 {
    color: #007bff;
    margin: 0;
}

/* Content with header offset */
#page-content-wrapper {
    padding-top: 60px;
}
```

### Добавьте эти HTML элементы после открывающего тега <body> но перед <div id="wrapper">:

```html
<!-- Login Modal -->
<div id="login-modal" class="login-modal">
    <div class="login-box">
        <div class="login-logo">
            <i class="bi bi-airplane" style="font-size: 48px; color: #007bff;"></i>
            <h2>Aviation MRO</h2>
            <p class="text-muted">Please login to continue</p>
        </div>
        <form id="login-form">
            <div class="mb-3">
                <label class="form-label">Username</label>
                <input type="text" class="form-control" id="login-username" required>
            </div>
            <div class="mb-3">
                <label class="form-label">Password</label>
                <input type="password" class="form-control" id="login-password" required>
            </div>
            <button type="submit" class="btn btn-primary w-100">Login</button>
        </form>
        <div id="login-error" class="alert alert-danger mt-3" style="display: none;"></div>
    </div>
</div>

<!-- User Header Bar -->
<div class="user-header">
    <h5 class="mb-0" id="page-title">Dashboard</h5>
    <div class="user-icon-group">
        <!-- Add User Button (Admin only) -->
        <button class="user-icon-btn" id="add-user-btn" style="display: none;" title="Add User">
            <i class="bi bi-person-plus"></i>
        </button>
        
        <!-- Settings Button -->
        <button class="user-icon-btn" id="settings-btn" title="Settings">
            <i class="bi bi-gear"></i>
        </button>
        
        <!-- Notifications Button -->
        <button class="user-icon-btn" id="notifications-btn" title="Notifications">
            <i class="bi bi-bell"></i>
            <span class="notification-badge" id="notification-count" style="display: none;">0</span>
        </button>
        
        <!-- User Profile -->
        <div class="user-avatar" id="user-profile-btn" title="Profile">
            <span id="user-initials">U</span>
        </div>
    </div>
</div>

<!-- Profile Dropdown -->
<div class="profile-dropdown" id="profile-dropdown">
    <div class="profile-header">
        <div class="avatar-placeholder" id="profile-avatar">U</div>
        <div><strong id="profile-name">User Name</strong></div>
        <div class="text-muted small" id="profile-position">Position</div>
        <div class="badge bg-primary mt-1" id="profile-role">viewer</div>
    </div>
    <div class="profile-dropdown-item" onclick="editProfile()">
        <i class="bi bi-person-circle"></i>
        <span>Edit Profile</span>
    </div>
    <div class="profile-dropdown-item" onclick="changePassword()">
        <i class="bi bi-key"></i>
        <span>Change Password</span>
    </div>
    <div class="profile-dropdown-item" onclick="logout()">
        <i class="bi bi-box-arrow-right"></i>
        <span>Logout</span>
    </div>
</div>

<!-- Notifications Panel -->
<div class="notifications-panel" id="notifications-panel">
    <div class="notifications-header">
        <strong>Notifications</strong>
        <button class="btn btn-sm btn-link" onclick="markAllNotificationsRead()">Mark all read</button>
    </div>
    <div class="notifications-list" id="notifications-list">
        <div class="text-center text-muted py-4">No notifications</div>
    </div>
</div>
```

### Добавьте JavaScript перед закрывающим тегом </body>:

Я создам отдельный файл с полным JavaScript кодом...
