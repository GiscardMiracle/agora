// Pure helpers of static/app.js (colour scale, filters, sort). Run with: node tests/test_front.js
const fs = require("fs");
const path = require("path");
const src = fs.readFileSync(path.join(__dirname, "../static/app.js"), "utf8");
const between = (a, b) => src.slice(src.indexOf(a), src.indexOf(b));
const code = [
  src.match(/const isActive[^\n]*\n/)[0], src.match(/const isKo[^\n]*\n/)[0],
  between("function scorePct", "function scoreCell"),
  between("// The colour scale", "const badge"),
  between("const STATUS_FILTERS", "function tabRepos"),
].join("\n");
const assert = require("assert");
const t = new Function(code + "; return { tone, levelTone, filterRepos, sortRepos };")();

// tone: 100 green, high yellow, middling orange, low or real failure red
assert.equal(t.tone("success", "100/100"), "ok");
assert.equal(t.tone("success", null), "ok");
assert.equal(t.tone("failed", "129/129"), "good", "a failed run is never green, even at 100%");
assert.equal(t.tone("failed", "90/100"), "good");
assert.equal(t.tone("failed", "70/100"), "good");
assert.equal(t.tone("failed", "69/100"), "mid");
assert.equal(t.tone("failed", "30/100"), "mid");
assert.equal(t.tone("failed", "29/100"), "ko");
assert.equal(t.tone("failed", "27/129"), "ko");
assert.equal(t.tone("failed", null), "ko");
assert.equal(t.tone("timeout", "50%"), "mid");
assert.equal(t.tone("timeout", null), "ko");
assert.equal(t.tone("error", "90/100"), "ko", "clone / docker errors are always red");
assert.equal(t.tone("running", "3/10"), "run");
assert.equal(t.tone("queued", null), "queued");
assert.equal(t.tone("cancelled", null), "none");
assert.equal(t.tone(null, null), "none");
assert.equal(t.levelTone(100), "ok");
assert.equal(t.levelTone(99.9), "good");

const R = [
  { name: "b", url: "u/b", status: "failed", score: "3/10" },
  { name: "a", url: "u/a", status: "success", score: "10/10" },
  { name: "c", url: "u/c", status: null },
  { name: "d2", url: "u/d", status: "running" },
  { name: "d10", url: "x", status: "timeout", score: "5/10" },
  { name: "e", url: "u/e", status: "failed", score: "9/10" },
  { name: "f", url: "u/f", status: "error" },
];
const names = (l) => l.map((r) => r.name);
assert.deepEqual(names(t.filterRepos(R, "", "ko")), ["b", "d10", "e", "f"]);
assert.deepEqual(names(t.filterRepos(R, "", "red")), ["f"]);
assert.deepEqual(names(t.filterRepos(R, "", "partial")), ["b", "d10", "e"]);
assert.deepEqual(names(t.filterRepos(R, "", "none")), ["c"]);
assert.deepEqual(names(t.filterRepos(R, "", "active")), ["d2"]);
assert.deepEqual(names(t.filterRepos(R, "A", "")), ["a"]);
assert.deepEqual(names(t.sortRepos(R, "name")), ["a", "b", "c", "d2", "d10", "e", "f"]);
assert.deepEqual(names(t.sortRepos(R, "score")).slice(0, 4), ["a", "e", "d10", "b"]);
console.log("front helpers ok");
