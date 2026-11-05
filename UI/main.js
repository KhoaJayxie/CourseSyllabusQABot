'use strict';

const $ = (selector) => document.querySelector(selector);

const els = {
  form: $('#chat-form'),
  input: $('#message-input'),
  send: $('#send-btn'),
  scroller: $('#messages'),
  list: $('#message-list'),
  empty: $('#empty-state'),
  title: $('#chat-title'),
  newChat: $('#new-chat-btn'),
  sidebarToggle: $('#sidebar-toggle'),
  chatList: $('#chat-list'),
  tplUser: $('#tpl-user'),
  tplAssistant: $('#tpl-assistant'),
};

const DEFAULT_TITLE = 'Cuộc trò chuyện mới';
const TYPING_TICK_MS = 18;
const NEAR_BOTTOM_PX = 120;
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

const state = {
  busy: false,
  session: 0,
  controller: null,
  chats: [],
  activeChatId: null,
};

const truncate = (text, max) => {
  const oneLine = text.replace(/\s+/g, ' ');
  return oneLine.length > max ? oneLine.slice(0, max - 1) + '…' : oneLine;
};

function getActiveChat() {
  return state.chats.find((chat) => chat.id === state.activeChatId);
}

function scrollToBottom(smooth = true) {
  els.scroller.scrollTo({
    top: els.scroller.scrollHeight,
    behavior: smooth && !reduceMotion ? 'smooth' : 'instant',
  });
}

function isNearBottom() {
  const { scrollHeight, scrollTop, clientHeight } = els.scroller;
  return scrollHeight - scrollTop - clientHeight < NEAR_BOTTOM_PX;
}

const supportsFieldSizing = window.CSS && CSS.supports('field-sizing', 'content');

function autoGrow() {
  if (supportsFieldSizing) return;
  els.input.style.height = 'auto';
  els.input.style.height = Math.min(els.input.scrollHeight, 192) + 'px';
}

function syncSendButton() {
  els.send.disabled = state.busy || els.input.value.trim() === '';
}

function setBusy(value) {
  state.busy = value;
  syncSendButton();
}

function addMessage(role, text = '') {
  const template = role === 'user' ? els.tplUser : els.tplAssistant;
  const root = template.content.firstElementChild.cloneNode(true);
  const textEl = root.querySelector('[data-text]');
  textEl.textContent = text;
  els.list.append(root);
  els.empty.classList.add('hidden');
  return {
    root,
    textEl,
    actions: root.querySelector('[data-actions]'),
    sources: root.querySelector('[data-sources]'),
  };
}

function renderSources(container, sources) {
  container.replaceChildren();
  if (!sources.length) {
    container.classList.add('hidden');
    return;
  }

  const heading = document.createElement('p');
  heading.className = 'text-sm font-medium text-chat-mute';
  heading.textContent = `Nguồn tham khảo (${sources.length})`;
  container.append(heading);

  sources.forEach((source) => {
    const item = document.createElement('details');
    item.className = 'rounded-lg border border-chat-line/70 bg-white/5 px-3 py-2';

    const summary = document.createElement('summary');
    summary.className = 'cursor-pointer text-sm text-chat-text';
    summary.textContent = `[${source.id}] ${source.title} — ${source.citation}`;

    const provenance = document.createElement('p');
    provenance.className = 'mt-2 text-xs font-medium text-sky-300';
    const originLabels = {
      hybrid: 'Hybrid',
      graph: 'Được graph mở rộng',
      'hybrid+graph': 'Hybrid + graph',
      'hybrid+rrf+jina': 'Dense + BM25 + RRF + Jina reranker',
    };
    provenance.textContent = `${originLabels[source.retrieval_origin] || 'Nguồn gốc retrieval không rõ'} · ${source.chunk_id || 'không có chunk_id'}`;
    if (Number.isFinite(source.rerank_score) && Number.isFinite(source.rrf_score)) {
      provenance.textContent += ` · rerank ${source.rerank_score.toFixed(3)} · RRF ${source.rrf_score.toFixed(4)}`;
    }

    const sourceText = document.createElement('p');
    sourceText.className = 'mt-2 whitespace-pre-wrap text-sm leading-6 text-chat-mute';
    sourceText.textContent = source.text;
    item.append(summary, provenance, sourceText);
    if (Array.isArray(source.graph_relations) && source.graph_relations.length) {
      const relationList = document.createElement('ul');
      relationList.className = 'mt-2 space-y-1 text-xs text-chat-mute';
      source.graph_relations.forEach((relation) => {
        const relationItem = document.createElement('li');
        relationItem.textContent = `Graph: ${relation.subject} —${relation.predicate}→ ${relation.object}; bằng chứng: “${relation.evidence}”`;
        relationList.append(relationItem);
      });
      item.append(relationList);
    }
    if (source.type === 'truyen_thuyet') {
      const note = document.createElement('p');
      note.className = 'mt-2 text-xs text-chat-mute';
      note.textContent = 'Nguồn được phân loại là truyền thuyết trong dữ liệu.';
      item.append(note);
    }
    container.append(item);
  });
  container.classList.remove('hidden');
}

function showActions(message) {
  message.actions.classList.remove('hidden');
  message.actions.classList.add('flex');
}

function renderChatList() {
  els.chatList.replaceChildren();
  state.chats.forEach((chat) => {
    const item = document.createElement('li');
    const link = document.createElement('button');
    const active = chat.id === state.activeChatId;
    link.type = 'button';
    link.dataset.chatId = chat.id;
    link.setAttribute('aria-current', active ? 'page' : 'false');
    link.className = active
      ? 'block w-full truncate rounded-lg bg-chat-hover px-3 py-2 text-left text-sm'
      : 'block w-full truncate rounded-lg px-3 py-2 text-left text-sm text-chat-text/90 hover:bg-chat-hover';
    link.textContent = chat.title;
    item.append(link);
    els.chatList.append(item);
  });
}

function renderChat() {
  const chat = getActiveChat();
  els.title.textContent = chat.title;
  els.list.replaceChildren();
  els.empty.classList.toggle('hidden', chat.messages.length > 0);

  chat.messages.forEach((message) => {
    const rendered = addMessage(message.role, message.text);
    if (message.role === 'assistant') {
      renderSources(rendered.sources, message.sources || []);
      if (message.text) showActions(rendered);
      if (message.error) rendered.textEl.classList.add('text-red-300');
    }
  });
  renderChatList();
  scrollToBottom(false);
}

function typeText(element, text, session) {
  return new Promise((resolve) => {
    if (reduceMotion) {
      element.textContent = text;
      resolve(true);
      return;
    }
    let shown = 0;
    const tick = () => {
      if (session !== state.session) return resolve(false);

      const stick = isNearBottom();
      shown = Math.min(text.length, shown + 1 + Math.floor(Math.random() * 3));
      element.textContent = text.slice(0, shown);
      if (stick) scrollToBottom(false);

      if (shown >= text.length) return resolve(true);
      setTimeout(tick, TYPING_TICK_MS);
    };
    tick();
  });
}

async function requestAnswer(question, signal) {
  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
    signal,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `Máy chủ trả về lỗi ${response.status}.`);
  }
  if (typeof payload.answer !== 'string' || !Array.isArray(payload.sources)) {
    throw new Error('Phản hồi từ máy chủ không đúng định dạng.');
  }
  return payload;
}

async function respond(rendered, message, session) {
  setBusy(true);
  rendered.actions.classList.add('hidden');
  rendered.actions.classList.remove('flex');
  rendered.textEl.textContent = '';
  rendered.textEl.classList.remove('text-red-300');
  rendered.textEl.classList.add('typing-caret');
  rendered.sources.classList.add('hidden');

  const controller = new AbortController();
  state.controller = controller;
  try {
    const result = await requestAnswer(message.question, controller.signal);
    if (session !== state.session) return;

    const finished = await typeText(rendered.textEl, result.answer, session);
    if (!finished) return;
    message.text = result.answer;
    message.sources = result.sources;
    renderSources(rendered.sources, result.sources);
    showActions(rendered);
  } catch (error) {
    if (error.name === 'AbortError' || session !== state.session) return;
    message.text = `Không thể xử lý câu hỏi: ${error.message}`;
    message.error = true;
    rendered.textEl.textContent = message.text;
    rendered.textEl.classList.add('text-red-300');
    showActions(rendered);
  } finally {
    if (session === state.session) {
      rendered.textEl.classList.remove('typing-caret');
      state.controller = null;
      setBusy(false);
    }
  }
}

function sendMessage(text) {
  const chat = getActiveChat();
  const session = state.session;
  if (chat.messages.length === 0) {
    chat.title = truncate(text, 40);
    els.title.textContent = chat.title;
    renderChatList();
  }

  chat.messages.push({ role: 'user', text });
  const assistantMessage = {
    role: 'assistant',
    text: '',
    sources: [],
    question: text,
  };
  chat.messages.push(assistantMessage);

  addMessage('user', text);
  const rendered = addMessage('assistant');
  rendered.textEl.classList.add('typing-caret');
  scrollToBottom();
  respond(rendered, assistantMessage, session);
}

els.form.addEventListener('submit', (event) => {
  event.preventDefault();
  const text = els.input.value.trim();
  if (!text || state.busy) return;

  els.input.value = '';
  autoGrow();
  syncSendButton();
  sendMessage(text);
  els.input.focus();
});

els.input.addEventListener('input', () => {
  autoGrow();
  syncSendButton();
});

els.input.addEventListener('keydown', (event) => {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return;
  if (window.matchMedia('(pointer: coarse)').matches) return;
  event.preventDefault();
  els.form.requestSubmit();
});

els.chatList.addEventListener('click', (event) => {
  const button = event.target.closest('[data-chat-id]');
  if (!button || button.dataset.chatId === state.activeChatId) return;
  cancelPendingResponse();
  state.activeChatId = button.dataset.chatId;
  renderChat();
  els.sidebarToggle.checked = false;
});

els.list.addEventListener('click', async (event) => {
  const button = event.target.closest('[data-action]');
  if (!button) return;

  const root = button.closest('[data-role="assistant"]');
  const textEl = root.querySelector('[data-text]');
  const messageIndex = Array.from(els.list.children).indexOf(root);
  const chat = getActiveChat();
  const message = chat.messages[messageIndex];

  if (button.dataset.action === 'copy') {
    try {
      await navigator.clipboard.writeText(textEl.textContent);
    } catch {
      button.title = 'Không thể sao chép trong trình duyệt này.';
      return;
    }
    const icon = button.querySelector('use');
    icon.setAttribute('href', '#i-check');
    setTimeout(() => icon.setAttribute('href', '#i-copy'), 1500);
  }

  if (button.dataset.action === 'regenerate' && !state.busy && message?.question) {
    const rendered = {
      root,
      textEl,
      actions: root.querySelector('[data-actions]'),
      sources: root.querySelector('[data-sources]'),
    };
    message.text = '';
    message.sources = [];
    message.error = false;
    respond(rendered, message, state.session);
  }
});

function cancelPendingResponse() {
  if (!state.busy) return;
  state.session += 1;
  state.controller?.abort();
  const chat = getActiveChat();
  const pending = [...chat.messages]
    .reverse()
    .find((message) => message.role === 'assistant' && !message.text);
  if (pending) {
    pending.text = 'Yêu cầu đã dừng khi chuyển cuộc trò chuyện.';
    pending.error = true;
  }
  state.controller = null;
  setBusy(false);
}

function newChat() {
  cancelPendingResponse();
  state.chats.unshift({
    id: crypto.randomUUID(),
    title: DEFAULT_TITLE,
    messages: [],
  });
  state.activeChatId = state.chats[0].id;
  els.input.value = '';
  autoGrow();
  setBusy(false);
  renderChat();
  els.scroller.scrollTop = 0;
  els.sidebarToggle.checked = false;
  els.input.focus();
}

els.newChat.addEventListener('click', newChat);

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') els.sidebarToggle.checked = false;
});

state.chats.push({
  id: crypto.randomUUID(),
  title: DEFAULT_TITLE,
  messages: [],
});
state.activeChatId = state.chats[0].id;
renderChat();
syncSendButton();
