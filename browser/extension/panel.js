// The Nova panel: the same conversation as the Nova window, live. Messages go through the background worker.
"use strict";
const port = chrome.runtime.connect({ name: "panel" });
const log = document.getElementById("log");
const STATES = { idle: ["Ready", "live"], listening: ["Listening", "busy"], thinking: ["Thinking", "busy"],
                 speaking: ["Talking", "busy"], approval: ["Needs your OK", "ask"], paused: ["Paused", ""] };
let asks = [];

function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
function add(node) { log.querySelector(".empty")?.remove(); log.append(node); log.scrollTop = log.scrollHeight; return node; }
function setState(name) {
  const [label, cls] = STATES[name] || STATES.idle;
  document.getElementById("state").textContent = label;
  document.getElementById("dot").className = "dot " + cls;
}
function empty() { if (!log.children.length) log.append(el("p", "empty", "Ask Nova anything, or tell it what to do in this browser: “open my GitHub notifications”, “summarise this page”.")); }

port.onMessage.addListener(msg => {
  if (msg.type === "status") { if (!msg.connected) { document.getElementById("state").textContent = "Nova isn't running"; } return; }
  if (msg.type === "history") {
    log.replaceChildren();
    for (const e of msg.items.slice().reverse()) { add(el("div", "msg user", e.request)); add(el("div", "msg nova", e.reply)); }
    return empty();
  }
  if (msg.type !== "event") return;
  const ev = msg.event;
  if (ev.event === "bar") setState(ev.state);
  else if (ev.event === "state") setState(ev.paused ? "paused" : ev.phase === "idle" ? "idle" : "thinking");
  else if (ev.event === "heard" && ev.source !== "chat") add(el("div", "msg user", ev.text));
  else if (ev.event === "step") add(el("div", "step", ev.text));
  else if (ev.event === "reply") add(el("div", "msg nova", ev.reply));
  else if (ev.event === "note") add(el("div", "note", ev.text));
  else if (ev.event === "asking") {
    const box = add(el("div", "ask"));
    box.append(el("b", null, `${ev.who} needs your OK`), el("div", null, `It wants to run something that ${ev.reason}:`), el("pre", null, ev.summary));
    const btns = el("div", "btns"), allow = el("button", "primary", "Allow"), deny = el("button", null, "Deny");
    allow.onclick = () => port.postMessage({ op: "approve", ok: true });
    deny.onclick = () => port.postMessage({ op: "approve", ok: false });
    btns.append(allow, deny); box.append(btns); asks.push(box);
  } else if (ev.event === "approval") {
    const box = asks.shift();
    if (box) box.querySelector(".btns").replaceChildren(el("span", "note", ev.allowed ? "Allowed" : "Denied"));
  }
});

const input = document.getElementById("input");
function send() {
  const text = input.value.trim(); if (!text) return;
  add(el("div", "msg user", text));
  port.postMessage({ op: "ask", text });
  input.value = "";
}
document.getElementById("send").onclick = send;
document.getElementById("mic").onclick = () => port.postMessage({ op: "listen" });
input.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
empty();
