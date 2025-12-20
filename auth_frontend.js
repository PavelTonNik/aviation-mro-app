// === AUTHENTICATION & USER MANAGEMENT JAVASCRIPT ===
// Добавьте этот код в конец вашего <script> блока в index.html

// === GLOBAL STATE ===
let currentUser = null;
let editingUserId = null;
let userCache = [];

// === AUTHENTICATION FUNCTIONS ===

async function handleLogin(event) {
    event.preventDefault();
    
    const username = document.getElementById('login-username').value;
    const password = document.getElementById('login-password').value;
    
    console.log('🔐 Login attempt:', username);
    
    try {
        const response = await fetch('/api/auth/login', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({username, password})
        });
        
        console.log('📡 Response status:', response.status);
        
        const data = await response.json();
        console.log('📦 Response data:', data);
        
        if (!response.ok) {
            throw new Error(data.detail || 'Login failed');
        }
        
        const user = data;
        currentUser = user;
        
        console.log('✅ Login success:', currentUser);
        
        // Save to sessionStorage
        sessionStorage.setItem('currentUser', JSON.stringify(user));
        
        // Hide login modal
        const modal = document.getElementById('login-modal');
        if (modal) {
            modal.style.display = 'none';
            console.log('🚪 Modal hidden');
        }
        
        // Initialize UI
        initializeUserInterface();
        
        // Load dashboard (if functions exist)
        if (typeof openDashboardView === 'function') {
            console.log('📊 Opening dashboard');
            openDashboardView();
        }
        if (typeof loadDashboardData === 'function') {
            console.log('📈 Loading dashboard data');
            loadDashboardData();
        }
        
    } catch (error) {
        console.error('❌ Login error:', error.message);
        const errorDiv = document.getElementById('login-error');
        if (errorDiv) {
            errorDiv.textContent = error.message;
            errorDiv.style.display = 'block';
        }
    }
}

function logout() {
    if (confirm('Are you sure you want to logout?')) {
        currentUser = null;
        sessionStorage.removeItem('currentUser');
        location.reload();
    }
}

function initializeUserInterface() {
    if (!currentUser) {
        console.warn('⚠️ currentUser is null');
        return;
    }
    
    console.log('👤 Initializing UI for:', currentUser.username, 'role:', currentUser.role);
    
    // Set user info
    const initials = (currentUser.first_name[0] + currentUser.last_name[0]).toUpperCase();
    
    const userInitials = document.getElementById('user-initials');
    if (userInitials) userInitials.textContent = initials;
    
    const profileAvatar = document.getElementById('profile-avatar');
    if (profileAvatar) profileAvatar.textContent = initials;
    
    const profileName = document.getElementById('profile-name');
    if (profileName) profileName.textContent = `${currentUser.first_name} ${currentUser.last_name}`;
    
    const profilePosition = document.getElementById('profile-position');
    if (profilePosition) profilePosition.textContent = currentUser.position || 'No position';
    
    const profileRole = document.getElementById('profile-role');
    if (profileRole) profileRole.textContent = currentUser.role;
    
    // Show/hide admin buttons
    if (currentUser.role === 'admin') {
        const btn = document.getElementById('add-user-btn');
        if (btn) {
            btn.style.display = 'flex';
            btn.style.visibility = 'visible';
            console.log('✅ Users button shown (admin)');
        }
    }
    
    // Load notifications
    loadNotifications();
    updateNotificationCount();
    
    // Start notification polling (every 30 seconds)
    setInterval(updateNotificationCount, 30000);
    
    console.log('✨ UI initialization complete');
}

// === PROFILE FUNCTIONS ===

document.getElementById('user-profile-btn')?.addEventListener('click', () => {
    const dropdown = document.getElementById('profile-dropdown');
    dropdown.classList.toggle('show');
    
    // Close other panels
    document.getElementById('notifications-panel').classList.remove('show');
});

function editProfile() {
    // TODO: Open profile edit modal
    alert('Profile editing coming soon!');
}

async function changePassword() {
    const oldPassword = prompt('Enter current password:');
    if (!oldPassword) return;
    
    const newPassword = prompt('Enter new password:');
    if (!newPassword) return;
    
    const confirmPassword = prompt('Confirm new password:');
    if (newPassword !== confirmPassword) {
        alert('Passwords do not match!');
        return;
    }
    
    try {
        const response = await fetch(`/api/users/${currentUser.id}/change-password`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                old_password: oldPassword,
                new_password: newPassword
            })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail);
        }
        
        alert('Password changed successfully!');
        
    } catch (error) {
        alert('Error: ' + error.message);
    }
}

// === NOTIFICATIONS FUNCTIONS ===

document.getElementById('notifications-btn')?.addEventListener('click', () => {
    const panel = document.getElementById('notifications-panel');
    panel.classList.toggle('show');
    
    // Close other panels
    document.getElementById('profile-dropdown').classList.remove('show');
    
    if (panel.classList.contains('show')) {
        loadNotifications();
    }
});

async function loadNotifications() {
    try {
        const response = await fetch('/api/notifications');
        if (!response.ok) return;
        
        const notifications = await response.json();
        const list = document.getElementById('notifications-list');
        
        if (notifications.length === 0) {
            list.innerHTML = '<div class="text-center text-muted py-4">No notifications</div>';
            return;
        }
        
        list.innerHTML = notifications.map(n => `
            <div class="notification-item ${n.is_read ? '' : 'unread'}" 
                 onclick="markNotificationRead(${n.id})">
                <div class="d-flex justify-content-between">
                    <strong>${n.entity_type}</strong>
                    <span class="badge bg-${getActionBadgeColor(n.action_type)}">${n.action_type}</span>
                </div>
                <div>${n.message}</div>
                <div class="notification-time">
                    by ${n.performed_by} • ${formatNotificationTime(n.created_at)}
                </div>
            </div>
        `).join('');
        
    } catch (error) {
        console.error('Error loading notifications:', error);
    }
}

async function updateNotificationCount() {
    try {
        const response = await fetch('/api/notifications/unread-count');
        if (!response.ok) return;
        
        const data = await response.json();
        const badge = document.getElementById('notification-count');
        
        if (data.count > 0) {
            badge.textContent = data.count > 99 ? '99+' : data.count;
            badge.style.display = 'block';
        } else {
            badge.style.display = 'none';
        }
        
    } catch (error) {
        console.error('Error updating notification count:', error);
    }
}

async function markNotificationRead(id) {
    try {
        await fetch(`/api/notifications/${id}/read`, {method: 'PUT'});
        loadNotifications();
        updateNotificationCount();
    } catch (error) {
        console.error('Error marking notification:', error);
    }
}

async function markAllNotificationsRead() {
    try {
        await fetch('/api/notifications/mark-all-read', {method: 'PUT'});
        loadNotifications();
        updateNotificationCount();
    } catch (error) {
        console.error('Error marking all notifications:', error);
    }
}

function getActionBadgeColor(action) {
    switch(action) {
        case 'created': return 'success';
        case 'updated': return 'info';
        case 'deleted': return 'danger';
        default: return 'secondary';
    }
}

function formatNotificationTime(timestamp) {
    const date = new Date(timestamp);
    const now = new Date();
    const diff = now - date;
    
    const minutes = Math.floor(diff / 60000);
    if (minutes < 1) return 'Just now';
    if (minutes < 60) return `${minutes}m ago`;
    
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    
    const days = Math.floor(hours / 24);
    if (days < 7) return `${days}d ago`;
    
    return date.toLocaleDateString();
}

// === USER MANAGEMENT (ADMIN ONLY) ===

document.getElementById('add-user-btn')?.addEventListener('click', openUserManager);
document.getElementById('refresh-users-btn')?.addEventListener('click', loadUsersList);
document.getElementById('user-form')?.addEventListener('submit', submitUserForm);
document.getElementById('user-reset-btn')?.addEventListener('click', resetUserForm);

async function openUserManager() {
    resetUserForm();
    await loadUsersList();
    const modalEl = document.getElementById('user-manage-modal');
    if (modalEl) {
        const modal = new bootstrap.Modal(modalEl);
        modal.show();
    }
}

function resetUserForm() {
    editingUserId = null;
    document.getElementById('user-id').value = '';
    document.getElementById('user-first-name').value = '';
    document.getElementById('user-last-name').value = '';
    document.getElementById('user-username').value = '';
    document.getElementById('user-password').value = '';
    document.getElementById('user-position').value = '';
    document.getElementById('user-role').value = 'viewer';
    document.getElementById('user-submit-btn').textContent = 'Create User';
}

function validateUsername(username) {
    return /^[A-Za-z0-9]+$/.test(username);
}

async function submitUserForm(event) {
    event.preventDefault();
    const first_name = document.getElementById('user-first-name').value.trim();
    const last_name = document.getElementById('user-last-name').value.trim();
    const username = document.getElementById('user-username').value.trim();
    const password = document.getElementById('user-password').value;
    const position = document.getElementById('user-position').value.trim();
    const role = document.getElementById('user-role').value;

    if (!validateUsername(username)) {
        showErrorNotification('Логин: только английские буквы и цифры.');
        return;
    }

    const payload = { first_name, last_name, username, position, role };
    if (!editingUserId) {
        payload.password = password;
    } else if (password) {
        // allow password change during edit when filled
        payload.password = password;
    }

    try {
        let response;
        if (editingUserId) {
            response = await fetch(`/api/users/${editingUserId}`, {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            });
        } else {
            response = await fetch('/api/users', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            });
        }

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Operation failed');
        }

        showSuccessNotification(editingUserId ? 'Пользователь обновлен' : 'Пользователь создан');
        await loadUsersList();
        resetUserForm();
    } catch (error) {
        showErrorNotification(error.message);
    }
}

async function loadUsersList() {
    try {
        const response = await fetch('/api/users');
        if (!response.ok) throw new Error('Не удалось загрузить пользователей');
        userCache = await response.json();
        renderUsersTable(userCache);
    } catch (error) {
        showErrorNotification(error.message);
    }
}

function renderUsersTable(users) {
    const tbody = document.getElementById('user-table-body');
    if (!tbody) return;
    tbody.innerHTML = users.map(u => `
        <tr>
            <td>${u.first_name}</td>
            <td>${u.last_name}</td>
            <td>${u.username}</td>
            <td><span class="badge bg-${u.role === 'admin' ? 'danger' : u.role === 'user' ? 'primary' : 'secondary'}">${u.role}</span></td>
            <td class="text-end">
                <button class="btn btn-outline-secondary btn-sm me-1" onclick="editUser(${u.id})"><i class="bi bi-pencil"></i></button>
                <button class="btn btn-outline-warning btn-sm me-1" onclick="resetUserPassword(${u.id})"><i class="bi bi-key"></i></button>
                <button class="btn btn-outline-danger btn-sm" onclick="deleteUser(${u.id})"><i class="bi bi-trash"></i></button>
            </td>
        </tr>
    `).join('');
}

function editUser(id) {
    const user = userCache.find(u => u.id === id);
    if (!user) return;
    editingUserId = id;
    document.getElementById('user-id').value = id;
    document.getElementById('user-first-name').value = user.first_name;
    document.getElementById('user-last-name').value = user.last_name;
    document.getElementById('user-username').value = user.username;
    document.getElementById('user-position').value = user.position || '';
    document.getElementById('user-role').value = user.role;
    document.getElementById('user-password').value = '';
    document.getElementById('user-submit-btn').textContent = 'Save User';
}

async function resetUserPassword(id) {
    const oldPassword = prompt('Введите текущий пароль пользователя');
    if (oldPassword === null) return;
    const newPassword = prompt('Введите новый пароль');
    if (!newPassword) return;
    try {
        const response = await fetch(`/api/users/${id}/change-password`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ old_password: oldPassword, new_password: newPassword })
        });
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Не удалось сменить пароль');
        }
        showSuccessNotification('Пароль обновлен');
    } catch (error) {
        showErrorNotification(error.message);
    }
}

async function deleteUser(id) {
    if (!confirm('Удалить пользователя?')) return;
    try {
        const response = await fetch(`/api/users/${id}`, { method: 'DELETE' });
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Не удалось удалить пользователя');
        }
        showSuccessNotification('Пользователь удален');
        await loadUsersList();
    } catch (error) {
        showErrorNotification(error.message);
    }
}

// === INITIALIZATION ===

document.addEventListener('DOMContentLoaded', () => {
    console.log('🔧 DOMContentLoaded event fired');
    
    // Check if user is logged in
    const savedUser = sessionStorage.getItem('currentUser');
    
    if (savedUser) {
        console.log('📝 User session found');
        currentUser = JSON.parse(savedUser);
        const modal = document.getElementById('login-modal');
        if (modal) modal.style.display = 'none';
        initializeUserInterface();
    } else {
        console.log('🔓 No session - showing login modal');
        // Show login modal
        const modal = document.getElementById('login-modal');
        if (modal) modal.style.display = 'flex';
    }
    
    // Setup login form
    const form = document.getElementById('login-form');
    console.log('🎯 Login form element:', form);
    
    if (form) {
        form.addEventListener('submit', handleLogin);
        console.log('✅ Login form listener attached');
    } else {
        console.error('❌ Login form not found!');
    }
    
    // Close dropdowns when clicking outside
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.user-icon-btn') && !e.target.closest('.profile-dropdown')) {
            const profileDropdown = document.getElementById('profile-dropdown');
            if (profileDropdown) profileDropdown.classList.remove('show');
        }
        if (!e.target.closest('.user-icon-btn') && !e.target.closest('.notifications-panel')) {
            const notifyPanel = document.getElementById('notifications-panel');
            if (notifyPanel) notifyPanel.classList.remove('show');
        }
    });
});

// === CREATE NOTIFICATIONS WHEN ACTIONS HAPPEN ===

// Helper function to send notification
async function sendNotification(actionType, entityType, entityId, message) {
    if (!currentUser) return;
    
    try {
        // This will be called automatically from backend, but you can also call it manually
        const performedBy = `${currentUser.first_name} ${currentUser.last_name}`;
        console.log(`Notification: ${actionType} ${entityType} by ${performedBy}`);
    } catch (error) {
        console.error('Error sending notification:', error);
    }
}
