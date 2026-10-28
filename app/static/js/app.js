/**
 * SPMS Core Client JavaScript
 * Theme switching, CSRF handling, Toast notifications, Notifications bell
 */

// Theme Controller
function initTheme() {
  const toggleBtn = document.getElementById('theme-toggle');
  const themeIcon = document.getElementById('theme-icon');

  function updateIcon(theme) {
    if (!themeIcon) return;
    if (theme === 'dark') {
      themeIcon.className = 'bi bi-sun-fill text-warning';
    } else {
      themeIcon.className = 'bi bi-moon-stars-fill text-primary';
    }
  }

  const currentTheme = document.documentElement.getAttribute('data-bs-theme') || 'light';
  updateIcon(currentTheme);

  if (toggleBtn) {
    toggleBtn.addEventListener('click', () => {
      const active = document.documentElement.getAttribute('data-bs-theme');
      const nextTheme = active === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-bs-theme', nextTheme);
      localStorage.setItem('spms-theme', nextTheme);
      updateIcon(nextTheme);
    });
  }
}

// Password toggle helper
function initPasswordToggles() {
  document.querySelectorAll('.password-toggle-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const targetId = btn.getAttribute('data-target');
      const input = document.getElementById(targetId);
      const icon = btn.querySelector('i');
      if (input) {
        if (input.type === 'password') {
          input.type = 'text';
          if (icon) icon.className = 'bi bi-eye-slash';
        } else {
          input.type = 'password';
          if (icon) icon.className = 'bi bi-eye';
        }
      }
    });
  });
}

// Bootstrap Toast initialization
function initToasts() {
  const toastElList = [].slice.call(document.querySelectorAll('.toast'));
  toastElList.map(function (toastEl) {
    const toast = new bootstrap.Toast(toastEl, { delay: 4000 });
    toast.show();
  });
}

// Notifications Bell & Dropdown controller
function initNotifications() {
  const badge = document.getElementById('notif-badge');
  const dropdown = document.querySelector('[aria-labelledby="notifDropdown"]');
  const emptyNotice = document.getElementById('notif-empty');
  if (!badge || !dropdown) return;

  async function checkNotifications() {
    try {
      const res = await fetch('/notifications/unread');
      if (!res.ok) return;
      const data = await res.json();
      
      if (data.count > 0) {
        badge.classList.remove('d-none');
        badge.setAttribute('title', `${data.count} unread notifications`);
      } else {
        badge.classList.add('d-none');
      }

      // Populate dropdown preview items
      const existingItems = dropdown.querySelectorAll('.notif-item');
      existingItems.forEach(el => el.remove());

      if (data.notifications && data.notifications.length > 0) {
        if (emptyNotice) emptyNotice.classList.add('d-none');
        data.notifications.forEach(n => {
          const li = document.createElement('li');
          li.className = 'notif-item';
          const a = document.createElement('a');
          a.className = 'dropdown-item small py-2 border-bottom text-wrap';
          a.href = n.link;
          
          const titleDiv = document.createElement('div');
          titleDiv.className = 'fw-bold text-primary';
          titleDiv.textContent = n.title; // escaped

          const msgDiv = document.createElement('div');
          msgDiv.className = 'text-secondary small text-truncate';
          msgDiv.textContent = n.message; // escaped

          const timeDiv = document.createElement('div');
          timeDiv.className = 'text-muted';
          timeDiv.style.fontSize = '0.72rem';
          timeDiv.textContent = n.created_at;

          a.appendChild(titleDiv);
          a.appendChild(msgDiv);
          a.appendChild(timeDiv);
          li.appendChild(a);

          dropdown.appendChild(li);
        });
      } else {
        if (emptyNotice) emptyNotice.classList.remove('d-none');
      }
    } catch (e) {}
  }

  checkNotifications();
  setInterval(checkNotifications, 8000);
}

document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  initPasswordToggles();
  initToasts();
  initNotifications();
});
