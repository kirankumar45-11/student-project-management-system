document.addEventListener('DOMContentLoaded', () => {
  const container = document.getElementById('chatContainer');
  const chatBox = document.getElementById('chatBox');
  const messageForm = document.getElementById('messageForm');
  const messageInput = document.getElementById('messageInput');
  if (!container || !chatBox) return;

  const assignmentId = container.getAttribute('data-assignment-id');

  function scrollToBottom() {
    if (chatBox) chatBox.scrollTop = chatBox.scrollHeight;
  }
  scrollToBottom();

  let lastMessageId = 0;
  const msgEls = document.querySelectorAll('[data-id]');
  if (msgEls.length > 0) {
    lastMessageId = parseInt(msgEls[msgEls.length - 1].getAttribute('data-id'), 10) || 0;
  }

  async function pollNewMessages() {
    try {
      const res = await fetch(`/messaging/${assignmentId}/poll?after_id=${lastMessageId}`);
      if (!res.ok) return;
      const data = await res.json();
      if (data.messages && data.messages.length > 0) {
        const emptyNotice = document.getElementById('noMessagesNotice');
        if (emptyNotice) emptyNotice.remove();

        data.messages.forEach(m => {
          if (m.id > lastMessageId) {
            lastMessageId = m.id;
            const wrapper = document.createElement('div');
            wrapper.className = `d-flex flex-column ${m.is_me ? 'align-items-end' : 'align-items-start'}`;
            wrapper.setAttribute('data-id', m.id);

            const bubble = document.createElement('div');
            bubble.className = `msg-bubble ${m.is_me ? 'msg-me' : 'msg-them'} shadow-sm`;
            bubble.textContent = m.content;

            const meta = document.createElement('span');
            meta.className = 'text-muted small mt-1 px-1';
            meta.style.fontSize = '0.75rem';
            meta.textContent = `${m.sender_name} • ${m.created_at}`;

            wrapper.appendChild(bubble);
            wrapper.appendChild(meta);
            chatBox.appendChild(wrapper);
          }
        });
        scrollToBottom();
      }
    } catch (e) {}
  }

  setInterval(pollNewMessages, 4000);

  if (messageInput && messageForm) {
    messageInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (messageInput.value.trim().length > 0) {
          messageForm.submit();
        }
      }
    });
  }
});
