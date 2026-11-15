// Fixed DOM adapter. Page content is data; no model-generated JavaScript is executed.
(() => {
  const visible = el => !!(el && el.isConnected && el.getClientRects().length);
  const composer = [...document.querySelectorAll('#prompt-textarea, textarea[data-testid="prompt-textarea"], main [contenteditable="true"], main textarea')]
    .find(el => visible(el) && el.getAttribute('type') !== 'password');
  const label = el => `${el.getAttribute('aria-label') || ''} ${el.getAttribute('data-testid') || ''} ${el.innerText || ''}`.trim();
  const buttons = [...document.querySelectorAll('button')].filter(visible);
  const send = buttons.find(el => el.dataset.testid === 'send-button') ||
    buttons.find(el => /^(send (message|prompt)|invia (messaggio|prompt)|invia)$/i.test((el.getAttribute('aria-label') || '').trim()));
  const busy = buttons.some(el => /stop-button|stop generating|interrompi (la )?generazione/i.test(label(el)));
  const main = document.querySelector('main');
  const assistants = main ? [...main.querySelectorAll('[data-message-author-role="assistant"]')] : [];
  const users = main ? [...main.querySelectorAll('[data-message-author-role="user"]')] : [];
  const rect = send && send.getBoundingClientRect();
  const challenge = /verify you are human|verifica di essere umano|just a moment|un momento/i.test(document.title) ||
    !!document.querySelector('iframe[src*="challenges.cloudflare.com"], #challenge-running');
  const login = !composer && buttons.some(el => /^(log in|sign in|accedi)$/i.test((el.innerText || '').trim()));
  return {
    url: location.href, title: document.title.slice(0, 150), composer_ready: !!composer,
    draft: composer ? (composer.value ?? composer.innerText ?? '').slice(0, 5000) : '',
    busy, challenge, login_required: login, user_count: users.length, assistant_count: assistants.length,
    last_user: users.length ? users.at(-1).innerText.slice(0, 5000) : '',
    last_reply: assistants.length ? assistants.at(-1).innerText.slice(0, 10000) : '',
    send: send && rect ? {enabled: !send.disabled && send.getAttribute('aria-disabled') !== 'true',
      x: rect.x + rect.width / 2, y: rect.y + rect.height / 2} : null
  };
})()
