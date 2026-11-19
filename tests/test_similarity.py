"""Run with: python -m unittest discover -s tests"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import similarity as sim  # noqa: E402

ORIGINAL = """
#include <stdio.h>
/* sorts the array */
int sum_sorted(int *tab, int len)
{
    int total = 0;
    for (int i = 0; i < len; i++) {
        for (int j = i + 1; j < len; j++) {
            if (tab[j] < tab[i]) {
                int tmp = tab[i];
                tab[i] = tab[j];
                tab[j] = tmp;
            }
        }
        total += tab[i] * 2;
    }
    printf("total: %d\\n", total);
    return total;
}
"""
RENAMED = ORIGINAL.replace("tab", "arr").replace("total", "acc").replace("len", "size").replace("tmp", "swap") \
    .replace("sorts the array", "totally different comment").replace("sum_sorted", "do_it")
OTHER = """
#include <stdlib.h>
char *my_strdup(const char *s)
{
    int n = 0;
    while (s[n] != 0)
        n++;
    char *out = malloc(n + 1);
    if (out == NULL)
        return NULL;
    for (int k = 0; k <= n; k++)
        out[k] = s[k];
    return out;
}
int my_abs(int x) { if (x < 0) { return -x; } return x; }
int my_max(int a, int b) { if (a > b) { return a; } return b; }
"""


def filler(seed: int, n: int = 25) -> str:
    """Code with a structure of its own (tokens differ, not just names or numbers)."""
    import random
    r = random.Random(seed)
    ops, kw = ["+", "-", "*", "/", "%", "&", "|", "^", "<<", ">>"], ["if", "while", "for"]
    out = []
    for i in range(n):
        body = f"x {r.choice(ops)} y {r.choice(ops)} (z {r.choice(ops)} x)"
        out.append(f"int f{i}(int x, int y, int z) {{ {r.choice(kw)} ({body} > 0) {{ return {body}; }} return z {r.choice(ops)} y; }}")
    return "\n".join(out)


def repo(files: dict[str, str]) -> Path:
    d = Path(tempfile.mkdtemp())
    for name, text in files.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return d


class Tokens(unittest.TestCase):
    def test_renaming_and_comments_do_not_matter(self):
        self.assertEqual(sim.tokens(ORIGINAL, ".c"), sim.tokens(RENAMED, ".c"))

    def test_python_hash_comments(self):
        self.assertEqual(sim.tokens("x = 1  # note\n", ".py"), sim.tokens("y = 2\n", ".py"))

    def test_c_preprocessor_kept(self):
        self.assertNotEqual(sim.tokens("#include <a.h>\n", ".c"), [])


class Compare(unittest.TestCase):
    def prints(self):
        a = sim.fingerprint(repo({"src/a.c": ORIGINAL + filler(1)}))
        b = sim.fingerprint(repo({"lib/other_name.c": RENAMED + filler(1)}))
        c = sim.fingerprint(repo({"x.c": OTHER + filler(2)}))
        return {1: a, 2: b, 3: c}

    def test_copy_found_unrelated_not(self):
        pairs = sim.compare(self.prints(), threshold=0.5)
        self.assertEqual([(p["a"], p["b"]) for p in pairs], [(1, 2)])
        self.assertGreater(pairs[0]["score"], 0.9)

    def test_boilerplate_shared_by_everyone_is_ignored(self):
        skeleton = filler(99, 40)
        prints = {i: sim.fingerprint(repo({"s.c": skeleton, "own.c": filler(i, 25)})) for i in range(8)}
        self.assertEqual(sim.compare(prints, threshold=0.9), [])

    def test_tiny_repos_are_not_compared(self):
        t = sim.fingerprint(repo({"m.c": "int main(void) { return 0; }"}))
        self.assertEqual(sim.compare({1: t, 2: set(t)}), [])

    def test_pack_roundtrip_and_skips(self):
        fp = sim.fingerprint(repo({"a.c": ORIGINAL, "node_modules/x.c": OTHER, "notes.txt": "int x = 1;" * 50}))
        self.assertEqual(sim.unpack(sim.pack(fp)), fp)
        self.assertEqual(fp, sim.fingerprint(repo({"a.c": ORIGINAL})))


if __name__ == "__main__":
    unittest.main()
