// Minimal streaming ANSI (SGR) -> HTML renderer. Other escape sequences are dropped.
class AnsiTerm {
  constructor(el) {
    this.el = el;
    this.pending = "";
    this.reset();
  }

  reset() {
    this.st = { fg: null, bg: null, bold: false, dim: false, italic: false, underline: false, inverse: false };
  }

  clear() {
    this.el.innerHTML = "";
    this.pending = "";
    this.reset();
  }

  static esc(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  static color256(n) {
    if (n < 16) return { cls: n };
    if (n < 232) {
      n -= 16;
      const v = (x) => (x ? x * 40 + 55 : 0);
      return { css: `rgb(${v(Math.floor(n / 36))},${v(Math.floor(n / 6) % 6)},${v(n % 6)})` };
    }
    const g = (n - 232) * 10 + 8;
    return { css: `rgb(${g},${g},${g})` };
  }

  sgr(params) {
    const p = params === "" ? [0] : params.split(";").map((x) => parseInt(x || "0", 10));
    const st = this.st;
    for (let i = 0; i < p.length; i++) {
      const c = p[i];
      if (c === 0) this.reset();
      else if (c === 1) st.bold = true;
      else if (c === 2) st.dim = true;
      else if (c === 3) st.italic = true;
      else if (c === 4) st.underline = true;
      else if (c === 7) st.inverse = true;
      else if (c === 22) st.bold = st.dim = false;
      else if (c === 23) st.italic = false;
      else if (c === 24) st.underline = false;
      else if (c === 27) st.inverse = false;
      else if (c >= 30 && c <= 37) st.fg = { cls: c - 30 };
      else if (c >= 90 && c <= 97) st.fg = { cls: c - 90 + 8 };
      else if (c === 39) st.fg = null;
      else if (c >= 40 && c <= 47) st.bg = { cls: c - 40 };
      else if (c >= 100 && c <= 107) st.bg = { cls: c - 100 + 8 };
      else if (c === 49) st.bg = null;
      else if (c === 38 || c === 48) {
        let col = null;
        if (p[i + 1] === 5) { col = AnsiTerm.color256(p[i + 2] || 0); i += 2; }
        else if (p[i + 1] === 2) { col = { css: `rgb(${p[i + 2] | 0},${p[i + 3] | 0},${p[i + 4] | 0})` }; i += 4; }
        if (c === 38) st.fg = col; else st.bg = col;
      }
    }
  }

  span(text) {
    text = text.replace(/[\x00-\x08\x0b-\x1f\x7f]/g, "");
    if (!text) return "";
    const st = this.st;
    let fg = st.fg, bg = st.bg;
    if (st.inverse) [fg, bg] = [bg || { cls: "fg" }, fg || { cls: "bg" }];
    const cls = [], style = [];
    if (fg) fg.css ? style.push(`color:${fg.css}`) : cls.push(`f${fg.cls}`);
    if (bg) bg.css ? style.push(`background:${bg.css}`) : cls.push(`b${bg.cls}`);
    if (st.bold) cls.push("ab");
    if (st.dim) cls.push("ad");
    if (st.italic) cls.push("ai");
    if (st.underline) cls.push("au");
    const t = AnsiTerm.esc(text);
    if (!cls.length && !style.length) return t;
    return `<span${cls.length ? ` class="${cls.join(" ")}"` : ""}${style.length ? ` style="${style.join(";")}"` : ""}>${t}</span>`;
  }

  write(chunk) {
    let buf = this.pending + chunk;
    this.pending = "";
    // Keep an unterminated escape sequence for the next chunk.
    const last = buf.lastIndexOf("\x1b");
    if (last !== -1 && buf.length - last < 256) {
      const tail = buf.slice(last);
      if (!/^\x1b(\[[0-9;?]*[@-~]|\][^\x07\x1b]*(\x07|\x1b\\)|[@-Z\\^_])/.test(tail)) {
        this.pending = tail;
        buf = buf.slice(0, last);
      }
    }
    buf = buf.replace(/\r+\n/g, "\n");
    const re = /\x1b(?:\[([0-9;?]*)([@-~])|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-Z\\^_])/g;
    let html = "", pos = 0, m;
    while ((m = re.exec(buf))) {
      html += this.span(buf.slice(pos, m.index));
      if (m[2] === "m" && !m[1].includes("?")) this.sgr(m[1]);
      pos = re.lastIndex;
    }
    html += this.span(buf.slice(pos));
    if (html) this.el.insertAdjacentHTML("beforeend", html);
  }
}
