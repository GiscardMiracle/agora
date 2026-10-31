#!/usr/bin/env python3
"""Reference for the 101pong test set.

ref.py x0 y0 z0 x1 y1 z1 n   prints the expected output
ref.py --random COUNT        prints COUNT valid argument lines (fixed seed)
"""
import math
import random
import sys


def expected(a):
    p0, p1, n = a[:3], a[3:6], int(a[6])
    v = [q - p for p, q in zip(p0, p1)]
    pos = [p + n * d for p, d in zip(p1, v)]
    out = "The velocity vector of the ball is:\n(%.2f, %.2f, %.2f)\n" % tuple(v)
    out += "At time t + %d, ball coordinates will be:\n(%.2f, %.2f, %.2f)\n" % (n, *pos)
    # The ball reaches z = 0 at t + s, with s = -z1 / vz. It must happen from t = 0 on.
    if v[2] != 0 and -p1[2] / v[2] >= 0:
        angle = math.degrees(math.asin(abs(v[2]) / math.sqrt(sum(d * d for d in v))))
        out += "The incidence angle is:\n%.2f degrees\n" % angle
    else:
        out += "The ball won't reach the paddle.\n"
    return out


def random_args(count):
    # Two decimals at most: results stay away from rounding ties, whatever formula the student uses.
    rng = random.Random(101)
    for _ in range(count):
        coords = ["%.2f" % rng.uniform(-100, 100) for _ in range(6)]
        print(*coords, rng.randint(0, 50))


if __name__ == "__main__":
    if sys.argv[1] == "--random":
        random_args(int(sys.argv[2]))
    else:
        sys.stdout.write(expected([float(x) for x in sys.argv[1:]]))
