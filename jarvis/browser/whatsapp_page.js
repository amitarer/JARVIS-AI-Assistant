(() => {
  const expected = /*EXPECTED*/;
  const visible = e => e && e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
  const text = e => e ? (e.innerText || e.textContent || '').trim() : '';
  const search = [...document.querySelectorAll('#side [contenteditable="true"][role="textbox"]')].filter(visible);
  const composers = [...document.querySelectorAll('#main footer [contenteditable="true"][role="textbox"]')].filter(visible);
  const header = document.querySelector('#main header');
  const titles = header ? [...header.querySelectorAll('[title]')].filter(visible) : [];
  const recipient = titles.length ? titles[0].getAttribute('title').trim() : '';
  const sends = [...document.querySelectorAll('#main footer [data-icon="send"]')].filter(visible);
  let send = null;
  if (sends.length === 1) {
    const button = sends[0].closest('button,[role="button"]') || sends[0];
    const r = button.getBoundingClientRect();
    send = {x: r.x+r.width/2, y: r.y+r.height/2, enabled: !button.disabled && button.getAttribute('aria-disabled') !== 'true'};
  }
  const matching = expected ? [...document.querySelectorAll('#main .message-out')].filter(row =>
    [...row.querySelectorAll('.selectable-text')].some(e => text(e) === expected)).length : 0;
  return {
    ready: search.length === 1,
    login_required: !search.length && !!document.querySelector('canvas,[data-testid="qrcode"],[data-ref]'),
    composer_ready: composers.length === 1,
    recipient, draft: composers.length === 1 ? text(composers[0]) : '',
    send, matching_outgoing: matching
  };
})()
