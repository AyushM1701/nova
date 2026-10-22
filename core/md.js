// The replies' markdown, shared by the Nova window (app.html) and the phone page (phone.html): phone.page() puts this
// file at each page's md.js marker. Escaped first, then only bold, italics, code, web links, lists and paragraphs.
"use strict";
const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
function inline(s) {
  return esc(s).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')  // links, web only
    .replace(/(^|[^*\w])\*([^*\s][^*]*)\*(?!\w)/g, "$1<em>$2</em>");
}
function blocks(src) {  // a list split by blank lines stays one list, so "1. … 2. …" keeps counting
  let html = "", list = null;
  const close = () => { if (list) { html += `</${list}>`; list = null; } };
  for (const para of src.split(/\n{2,}/)) {
    const lines = para.split("\n").filter(l => l.trim());
    if (!lines.length) continue;
    const ul = lines.every(l => /^\s*[-*•]\s+/.test(l)), ol = lines.every(l => /^\s*\d+[.)]\s+/.test(l));
    if (ul || ol) {
      const tag = ul ? "ul" : "ol"; if (list !== tag) { close(); html += `<${tag}>`; list = tag; }
      html += lines.map(l => `<li>${inline(l.replace(/^\s*([-*•]|\d+[.)])\s+/, ""))}</li>`).join("");
    } else { close(); html += `<p>${lines.map(inline).join("<br>")}</p>`; }
  }
  close(); return html;
}
function md(text) {
  const parts = String(text || "").split(/```[\w-]*\n?([\s\S]*?)```/g);
  return parts.map((p, i) => i % 2 ? `<pre><code>${esc(p.replace(/\n$/, ""))}</code></pre>` : blocks(p)).join("");
}
