// Nova's browser extension: one WebSocket to Nova on 127.0.0.1 (nothing else, ever). Nova sends tool calls
// ({id, tool, args}) and live events; this worker runs the tools in your real browser profile and keeps the
// panel and the toolbar badge in sync. Safety decisions (what needs your OK, what is blocked) are made by Nova.
"use strict";

const state = { ws: null, cfg: null, bar: "idle", ports: new Set(), doneTimer: null, retry: null, wait: 1000 };

async function config() {
  if (!state.cfg) state.cfg = await (await fetch(chrome.runtime.getURL("nova.json"))).json();
  return state.cfg;
}

async function connect() {
  clearTimeout(state.retry);
  if (state.ws && state.ws.readyState <= 1) return;
  let cfg;
  try { cfg = await config(); } catch { return; }  // installed without nova.json: nothing to talk to
  if (state.ws && state.ws.readyState <= 1) return;  // another connect() got here first
  const ws = new WebSocket(`ws://127.0.0.1:${cfg.port}`);
  state.ws = ws;
  ws.onopen = () => {
    ws.send(JSON.stringify({ type: "hello", token: cfg.token, browser: cfg.browser,
                             version: chrome.runtime.getManifest().version }));
    badge("idle");
  };
  ws.onmessage = e => {
    state.wait = 1000;  // Nova answered, so the hello was accepted
    try { onNova(JSON.parse(e.data)); } catch (err) { console.error(err); }
  };
  ws.onclose = () => {
    if (state.ws !== ws) return;
    state.ws = null; state.cfg = null;  // re-read nova.json: Nova may have reinstalled us with a new token
    badge("off");
    // Nova restarted or isn't running yet: try again soon, backing off to every 5 s
    state.retry = setTimeout(connect, state.wait); state.wait = Math.min(state.wait * 2, 5000);
  };
  ws.onerror = () => {};
}

function send(msg) { if (state.ws && state.ws.readyState === 1) state.ws.send(JSON.stringify(msg)); }

// keep the worker alive: traffic on an open socket every 20 s keeps an MV3 worker running, and while Nova is
// away an extension API call does the same, so the retries above keep going instead of the worker going idle
setInterval(() => state.ws && state.ws.readyState === 1 ? send({ type: "ping" }) : chrome.runtime.getPlatformInfo(), 20000);
// the browser stopped the worker anyway: the alarm wakes it, and waking runs connect() below.
// Created only once, since creating it again on every wake would push its next run back.
chrome.alarms.get("nova-reconnect", a => a || chrome.alarms.create("nova-reconnect", { periodInMinutes: 0.5 }));
chrome.alarms.onAlarm.addListener(connect);
chrome.runtime.onStartup.addListener(connect);
chrome.runtime.onInstalled.addListener(() => {
  connect();
  // Brave and Chrome have a side panel; Opera GX doesn't, so there the toolbar button opens a popup instead
  if (chrome.sidePanel && chrome.sidePanel.setPanelBehavior) chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
  else chrome.action.setPopup({ popup: "panel.html" });
});
connect();

/* ---------- live sync: badge + panel ---------- */
const BADGES = {
  off: ["", "#555"], idle: ["", "#7b6dff"], listening: ["REC", "#e5484d"], thinking: ["…", "#7b6dff"],
  speaking: ["♪", "#7b6dff"], approval: ["OK?", "#ffba3c"], paused: ["II", "#555"], done: ["✓", "#3ecf8e"],
};
function badge(kind) {
  const [text, color] = BADGES[kind] || BADGES.idle;
  chrome.action.setBadgeText({ text });
  chrome.action.setBadgeBackgroundColor({ color });
  chrome.action.setTitle({ title: kind === "off" ? "Nova (not running)" : `Nova: ${kind}` });
}

function onNova(msg) {
  if (msg.type === "call") return runTool(msg);
  if (msg.type === "reload") return chrome.runtime.reload();  // Nova updated the files
  if (msg.type === "event") {
    const ev = msg.event;
    if (ev.event === "bar") {
      clearTimeout(state.doneTimer);
      badge(ev.state === "idle" && state.bar !== "idle" && state.bar !== "listening" ? "done" : ev.state);
      if (ev.state === "idle") state.doneTimer = setTimeout(() => badge("idle"), 4000);
      state.bar = ev.state;
    }
    if (ev.event === "asking") badge("approval");
  }
  for (const port of state.ports) port.postMessage(msg);  // the panel renders events and history replies
}

chrome.runtime.onConnect.addListener(port => {
  if (port.name !== "panel") return;
  state.ports.add(port);
  port.onDisconnect.addListener(() => state.ports.delete(port));
  port.onMessage.addListener(m => send({ type: "panel", ...m }));  // ask, approve, listen, history
  port.postMessage({ type: "status", connected: !!(state.ws && state.ws.readyState === 1) });
  send({ type: "panel", op: "history" });
});

/* ---------- tools ---------- */
// The agent window: pages the AI opens go to a window of their own that never takes focus, so the user's tabs and
// windows stay put. Its id lives in session storage because this service worker is stopped and restarted at will.
async function agentWindow() {
  const { agentWin } = await chrome.storage.session.get("agentWin");
  if (!agentWin) return null;
  try { return await chrome.windows.get(agentWin); }
  catch { await chrome.storage.session.remove("agentWin"); return null; }  // the user closed it
}

// a tool with no tab_id works on the agent window's page while there is one, else on the page the user is looking at
async function activeTab(tabId) {
  if (tabId) return chrome.tabs.get(tabId);
  const agent = await agentWindow();
  if (agent) {
    const [own] = await chrome.tabs.query({ active: true, windowId: agent.id });
    if (own) return own;
  }
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (!tab) throw new Error("No open tab. Open a window first.");
  return tab;
}

function loaded(tabId, timeout = 15000) {
  return new Promise(resolve => {
    const done = () => { chrome.tabs.onUpdated.removeListener(listen); clearTimeout(timer); resolve(); };
    const listen = (id, info) => { if (id === tabId && info.status === "complete") done(); };
    const timer = setTimeout(done, timeout);
    chrome.tabs.onUpdated.addListener(listen);
    chrome.tabs.get(tabId).then(t => { if (t.status === "complete") done(); }).catch(done);
  });
}

async function inPage(tabId, func, ...args) {
  const [res] = await chrome.scripting.executeScript({ target: { tabId }, func, args });
  if (res && res.result && res.result.error) throw new Error(res.result.error);
  return res ? res.result : null;
}

async function withDebugger(tabId, work) {
  const target = { tabId };
  await chrome.debugger.attach(target, "1.3");
  try { return await work((method, params) => chrome.debugger.sendCommand(target, method, params)); }
  finally { await chrome.debugger.detach(target).catch(() => {}); }  // the "being debugged" bar goes away
}

const inAgentWindow = async tab => (await agentWindow())?.id === tab.windowId;

const describeTab = t => ({ id: t.id, title: t.title, url: t.url, active: t.active, window: t.windowId, group: t.groupId });

// what you asked to see comes to the front: its tab active, its window focused and not minimized
async function bringForward(tab) {
  await chrome.tabs.update(tab.id, { active: true });
  const win = await chrome.windows.get(tab.windowId);
  await chrome.windows.update(tab.windowId, win.state === "minimized" ? { state: "normal", focused: true } : { focused: true });
}

function webOnly(url) {  // never a script, a data page or a file of this computer, whatever Nova let through
  if (/^\s*(javascript|data|file|blob|vbscript):/i.test(url || "")) throw new Error("Nova only opens web addresses.");
  return url;
}

const TOOLS = {
  async tabs({ action = "list", url, tab_id, tab_ids, title, background = false }) {
    if (action === "list") return (await chrome.tabs.query({})).map(describeTab);
    if (action === "open") {
      webOnly(url);
      if (!background) { const t = await chrome.tabs.create({ url: url || "about:blank" }); await bringForward(t); await loaded(t.id); return describeTab(await chrome.tabs.get(t.id)); }
      const agent = await agentWindow();
      let t;
      if (agent) t = await chrome.tabs.create({ windowId: agent.id, url: url || "about:blank", active: true });
      else {
        const win = await chrome.windows.create({ url: url || "about:blank", focused: false });  // not minimized: those load slowly
        await chrome.storage.session.set({ agentWin: win.id });
        t = win.tabs[0];
      }
      await loaded(t.id);
      return describeTab(await chrome.tabs.get(t.id));
    }
    if (action === "switch") {  // the user wants to see it: it comes to the front and is theirs from now on
      const t = await chrome.tabs.get(tab_id);
      await bringForward(t);
      if ((await agentWindow())?.id === t.windowId) await chrome.storage.session.remove("agentWin");
      return describeTab(await chrome.tabs.get(tab_id));
    }
    if (action === "close_agent") {  // the request is over: the window goes, unless something is playing in it
      const agent = await agentWindow();
      if (!agent) return "none";
      await chrome.storage.session.remove("agentWin");
      const playing = (await chrome.tabs.query({ windowId: agent.id })).find(t => t.audible);
      if (playing) { await bringForward(playing); return "kept: playing"; }
      await chrome.windows.remove(agent.id);
      return "closed";
    }
    if (action === "close") { await chrome.tabs.remove(tab_ids || tab_id); return "closed"; }
    if (action === "group") {
      const group = await chrome.tabs.group({ tabIds: tab_ids });
      if (title && chrome.tabGroups) await chrome.tabGroups.update(group, { title });
      return { group };
    }
    throw new Error(`Unknown tabs action ${action}`);
  },
  async navigate({ action = "go", url, tab_id }) {
    const tab = await activeTab(tab_id);
    if (action === "go") await chrome.tabs.update(tab.id, { url: webOnly(url) });
    else if (action === "back") await chrome.tabs.goBack(tab.id);
    else if (action === "forward") await chrome.tabs.goForward(tab.id);
    else if (action === "reload") await chrome.tabs.reload(tab.id);
    if (!(await inAgentWindow(tab))) await bringForward(tab);
    await new Promise(r => setTimeout(r, 300));
    await loaded(tab.id);
    return describeTab(await chrome.tabs.get(tab.id));
  },
  async read({ mode = "outline", tab_id }) {
    const tab = await activeTab(tab_id);
    return inPage(tab.id, readPage, mode);
  },
  async inspect({ ref, tab_id }) {
    const tab = await activeTab(tab_id);
    return inPage(tab.id, elementInfo, String(ref));
  },
  async click({ ref, tab_id }) {
    const tab = await activeTab(tab_id);
    const out = await inPage(tab.id, clickElement, String(ref));
    await new Promise(r => setTimeout(r, 600));
    await loaded(tab.id, 8000);
    return out;
  },
  async type({ ref, text, submit = false, tab_id }) {
    const tab = await activeTab(tab_id);
    return inPage(tab.id, typeInto, String(ref), String(text), !!submit);
  },
  async select({ ref, value, tab_id }) {
    const tab = await activeTab(tab_id);
    return inPage(tab.id, selectOption, String(ref), String(value));
  },
  async scroll({ direction = "down", ref, tab_id }) {
    const tab = await activeTab(tab_id);
    return inPage(tab.id, scrollPage, direction, ref ? String(ref) : null);
  },
  async press({ key, tab_id }) {
    const tab = await activeTab(tab_id);
    const keys = { Enter: [13, "\r"], Tab: [9, ""], Escape: [27, ""], ArrowDown: [40, ""], ArrowUp: [38, ""],
                   ArrowLeft: [37, ""], ArrowRight: [39, ""], Backspace: [8, ""], Space: [32, " "] };
    const [code, text] = keys[key] || [0, key.length === 1 ? key : ""];
    return withDebugger(tab.id, async cmd => {  // real key presses, which page scripts can't fake
      await cmd("Input.dispatchKeyEvent", { type: "keyDown", key, windowsVirtualKeyCode: code, text });
      await cmd("Input.dispatchKeyEvent", { type: "keyUp", key, windowsVirtualKeyCode: code });
      return `pressed ${key}`;
    });
  },
  async screenshot({ tab_id }) {
    const tab = await activeTab(tab_id);
    await chrome.tabs.update(tab.id, { active: true });
    if (!(await inAgentWindow(tab))) await chrome.windows.update(tab.windowId, { focused: true });
    await new Promise(r => setTimeout(r, 250));
    return { image: await chrome.tabs.captureVisibleTab(tab.windowId, { format: "png" }) };
  },
  async download({ url, filename }) {
    webOnly(url);
    if (filename && !/^[\w. -]{1,100}$/.test(filename)) throw new Error("The download's file name must be plain.");
    const id = await chrome.downloads.download(filename ? { url, filename } : { url });
    return { download: id };
  },
  async script({ code, tab_id }) {
    const tab = await activeTab(tab_id);
    return withDebugger(tab.id, async cmd => {
      const r = await cmd("Runtime.evaluate", { expression: code, returnByValue: true, awaitPromise: true });
      if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
      return r.result.value;
    });
  },
};

async function runTool({ id, tool, args }) {
  try {
    if (!TOOLS[tool]) throw new Error(`Unknown tool ${tool}`);
    send({ type: "result", id, ok: true, result: await TOOLS[tool](args || {}) });
  } catch (e) {
    send({ type: "result", id, ok: false, error: String(e && e.message || e) });
  }
}

/* ---------- functions that run inside the page (self-contained: no closures) ---------- */
function readPage(mode) {
  const visible = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none"; };
  const name = el => (el.getAttribute("aria-label") || (el.labels && el.labels[0] && el.labels[0].innerText) ||
    el.innerText || el.value || el.getAttribute("placeholder") || el.getAttribute("title") || el.getAttribute("alt") || "")
    .replace(/\s+/g, " ").trim().slice(0, 80);
  const head = `${document.title}\n${location.href}\n`;
  if (mode === "text") return head + "\n" + (document.body ? document.body.innerText : "").slice(0, 30000);
  const sel = "a[href],button,input,select,textarea,summary,[role=button],[role=link],[role=checkbox],[role=radio]," +
    "[role=tab],[role=menuitem],[role=option],[role=switch],[role=combobox],[role=textbox],[contenteditable=true]";
  let next = Number(document.documentElement.dataset.novaNext || 1);
  const lines = [];
  for (const el of document.querySelectorAll(`h1,h2,h3,${sel}`)) {
    if (!visible(el)) continue;
    if (/^H[1-3]$/.test(el.tagName)) { lines.push(`${"#".repeat(+el.tagName[1])} ${el.innerText.trim().slice(0, 100)}`); continue; }
    if (!el.dataset.novaRef) el.dataset.novaRef = String(next++);
    const role = el.getAttribute("role") || (el.tagName === "A" ? "link" : el.tagName === "INPUT" ? `input:${el.type}` : el.tagName.toLowerCase());
    // card numbers and one-time codes the user typed stay out of what the AI reads, like passwords
    // (by its name too, like Nova's typing rule: checkout pages often leave out autocomplete)
    const secret = el.type === "password" || /cc-|one-time-code/.test(el.getAttribute("autocomplete") || "") ||
      /pass|card|cvv|cvc|otp|one.?time|\bpin\b|\bssn\b|iban/i.test(`${el.name} ${el.id} ${el.getAttribute("placeholder") || ""}`) ||
      /^\D*(?:\d[ -]?){13,19}\D*$/.test(el.value || "");
    const value = (el.tagName === "INPUT" || el.tagName === "TEXTAREA") && !secret && el.value ? ` = "${el.value.slice(0, 60)}"` : "";
    lines.push(`[${el.dataset.novaRef}] ${role} "${name(el)}"${value}`);
    if (lines.length >= 500) { lines.push("… (more on the page; scroll and read again)"); break; }
  }
  document.documentElement.dataset.novaNext = String(next);
  return head + "\n" + lines.join("\n");
}

function elementInfo(ref) {  // ref "": the element that has focus
  const el = ref ? document.querySelector(`[data-nova-ref="${CSS.escape(ref)}"]`) : document.activeElement;
  if (!el) return { error: `No element [${ref}] on this page. Read the page again to get fresh refs.` };
  const label = (el.getAttribute("aria-label") || (el.labels && el.labels[0] && el.labels[0].innerText) || el.innerText ||
    el.value || el.getAttribute("placeholder") || el.getAttribute("name") || el.getAttribute("title") || "").replace(/\s+/g, " ").trim().slice(0, 120);
  const type = (el.getAttribute("type") || "").toLowerCase();
  const isSubmit = (el.tagName === "BUTTON" && (type === "submit" || (!type && !!el.form))) ||
    (el.tagName === "INPUT" && (type === "submit" || type === "image"));
  // a search box by its markup too, for sites whose box has no "search" in its name or placeholder
  const search = type === "search" || el.getAttribute("role") === "searchbox" || el.getAttribute("enterkeyhint") === "search" ||
    el.getAttribute("inputmode") === "search" || !!el.closest("[role=search]") ||
    /search|results/i.test(el.form ? el.form.getAttribute("action") || "" : "");
  return { tag: el.tagName.toLowerCase(), type, role: el.getAttribute("role") || "", name: label, search,
           field: [el.getAttribute("name"), el.id, el.getAttribute("placeholder"), el.getAttribute("aria-label"),
                   el.getAttribute("data-testid")].filter(Boolean).join(" "),
           autocomplete: (el.getAttribute("autocomplete") || "").toLowerCase(), inForm: !!el.form, isSubmit,
           formSecret: !!(el.form && el.form.querySelector("input[type=password], input[autocomplete^=cc-], input[autocomplete=one-time-code]")),
           href: el.href || "", url: location.href, host: location.host };
}

function clickElement(ref) {
  const el = document.querySelector(`[data-nova-ref="${CSS.escape(ref)}"]`);
  if (!el) return { error: `No element [${ref}] on this page. Read the page again.` };
  el.scrollIntoView({ block: "center", inline: "center" });
  el.focus({ preventScroll: true });
  el.click();
  return `clicked [${ref}]`;
}

function typeInto(ref, text, submit) {
  const el = document.querySelector(`[data-nova-ref="${CSS.escape(ref)}"]`);
  if (!el) return { error: `No element [${ref}] on this page. Read the page again.` };
  el.scrollIntoView({ block: "center" });
  el.focus();
  if (el.isContentEditable) {
    document.execCommand("selectAll"); document.execCommand("insertText", false, text);
  } else {  // the native setter, so React/Vue inputs notice the change
    const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), "value").set;
    setter.call(el, text);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }
  if (submit) {
    el.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", keyCode: 13, bubbles: true }));
    if (el.form) el.form.requestSubmit ? el.form.requestSubmit() : el.form.submit();
  }
  return `typed into [${ref}]${submit ? " and submitted" : ""}`;
}

function selectOption(ref, value) {
  const el = document.querySelector(`[data-nova-ref="${CSS.escape(ref)}"]`);
  if (!el || el.tagName !== "SELECT") return { error: `[${ref}] isn't a dropdown. Read the page again.` };
  const want = value.toLowerCase();
  const opt = [...el.options].find(o => o.value.toLowerCase() === want || o.text.trim().toLowerCase() === want) ||
              [...el.options].find(o => o.text.toLowerCase().includes(want));
  if (!opt) return { error: `No option "${value}". Options: ${[...el.options].map(o => o.text.trim()).join(", ").slice(0, 400)}` };
  el.value = opt.value;
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
  return `selected "${opt.text.trim()}"`;
}

function scrollPage(direction, ref) {
  if (ref) {
    const el = document.querySelector(`[data-nova-ref="${CSS.escape(ref)}"]`);
    if (!el) return { error: `No element [${ref}].` };
    el.scrollIntoView({ block: "center" });
    return `scrolled to [${ref}]`;
  }
  const h = innerHeight * 0.85;
  if (direction === "top") scrollTo(0, 0);
  else if (direction === "bottom") scrollTo(0, document.body.scrollHeight);
  else scrollBy(0, direction === "up" ? -h : h);
  return `scrolled ${direction}`;
}
