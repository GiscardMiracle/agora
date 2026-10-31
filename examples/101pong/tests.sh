#!/usr/bin/env bash
# Agora - 101pong test set.
# Runs in the sandbox: cwd = /work (student repo), this file + ref.py in /tests (read-only).
# Any language present in the image works. Output is compared byte by byte, except "-0.00" = "0.00".

BIN=./101pong
REF="python3 /tests/ref.py"
TMP=/tmp/agora
TEST_TIMEOUT=2
HAS_BIN=1

mkdir -p "$TMP"

# ------------------------------------------------------------------ display helpers
G=$'\e[1;32m' R=$'\e[1;31m' Y=$'\e[1;33m' B=$'\e[1;34m' C=$'\e[36m' M=$'\e[1;35m'
D=$'\e[2m' N=$'\e[0m'
PASS=0 TOTAL=0
declare -A S_PASS S_TOTAL
SECTIONS=()

section() { printf '\n%s━━ %s %s\n' "$B" "$1" "$N"; }

# show and run a command on the student's code
run() {
    printf '%s$ %s%s\n' "$M" "$*" "$N"
    "$@" 2>&1 | sed 's/^/    /'
    return "${PIPESTATUS[0]}"
}

# record <section> <ok:0|1> <label> [details...]
record() {
    local sec=$1 ok=$2 label=$3
    shift 3
    [ -z "${S_TOTAL[$sec]}" ] && { SECTIONS+=("$sec"); S_TOTAL[$sec]=0; S_PASS[$sec]=0; }
    S_TOTAL[$sec]=$((S_TOTAL[$sec] + 1))
    TOTAL=$((TOTAL + 1))
    if [ "$ok" -eq 0 ]; then
        S_PASS[$sec]=$((S_PASS[$sec] + 1))
        PASS=$((PASS + 1))
        printf '  %s✔%s %s\n' "$G" "$N" "$label"
    else
        printf '  %s✘%s %s\n' "$R" "$N" "$label"
    fi
    local line
    for line in "$@"; do printf '      %s\n' "$line"; done
}

summary() {
    section "summary"
    local sec color
    for sec in "${SECTIONS[@]}"; do
        color=$G
        [ "${S_PASS[$sec]}" -ne "${S_TOTAL[$sec]}" ] && color=$R
        [ "${S_PASS[$sec]}" -ne 0 ] && [ "$color" = "$R" ] && color=$Y
        printf '  %-14s %s%3d / %-3d%s\n' "$sec" "$color" "${S_PASS[$sec]}" "${S_TOTAL[$sec]}" "$N"
    done
    color=$R
    [ "$PASS" -eq "$TOTAL" ] && color=$G
    printf '\n%sAGORA_SCORE: %d/%d%s\n' "$color" "$PASS" "$TOTAL" "$N"
    [ "$PASS" -eq "$TOTAL" ]
    exit
}

# ------------------------------------------------------------------ running the program

# launch <args...>: fills $TMP/out, $TMP/err and $RC. LABEL = the exact command, quoted.
launch() {
    LABEL=$(printf '%q ' "$BIN" "$@")
    (timeout "$TEST_TIMEOUT" "$BIN" "$@" >"$TMP/out" 2>"$TMP/err" </dev/null; exit $?) 2>/dev/null
    RC=$?
}

# Error line when the program did not terminate by itself, nothing otherwise.
abnormal() {
    if [ "$RC" -eq 124 ]; then
        echo "${R}TIMEOUT${N} (> ${TEST_TIMEOUT}s)"
    elif [ "$RC" -gt 128 ]; then
        echo "${R}CRASH${N} (signal $((RC - 128))$([ $((RC - 128)) -eq 11 ] && echo ", segfault"))"
    fi
}

# one file per line, prefixed, like cat -e
show() { cat -e "$2" | sed "s/^/$1/"; }

stderr_lines() {
    [ -s "$TMP/err" ] && head -n 5 "$TMP/err" | cat -e | sed "s/^/${D}stderr: ${N}/"
}

no_neg_zero() { sed -E 's/-(0\.00)([^0-9]|$)/\1\2/g' "$1"; }

# compare_output <section> <expected file>: exit 0 + exact stdout. Expects launch to have run.
compare_output() {
    local sec=$1 file=$2 why details=()
    why=$(abnormal)
    [ -n "$why" ] && details+=("$why")
    if [ "$RC" -ne 0 ] && [ -z "$why" ]; then
        details+=("${R}exit $RC${N} ${D}(expected 0)${N}")
    fi
    if ! cmp -s <(no_neg_zero "$file") <(no_neg_zero "$TMP/out"); then
        mapfile -t -O "${#details[@]}" details < <(
            echo "${D}expected:${N}"; show "  " "$file"
            echo "${R}got:${N}"; show "  " "$TMP/out"; stderr_lines)
        record "$sec" 1 "$LABEL" "${details[@]}"
    elif [ ${#details[@]} -ne 0 ]; then
        record "$sec" 1 "$LABEL" "${details[@]}"
    else
        mapfile -t details < <(show "${D}" "$TMP/out" | sed "s/\$/${N}/"; stderr_lines)
        record "$sec" 0 "$LABEL" "${details[@]}"
    fi
}

# Program unavailable: count the test as failed without flooding the log.
skip_if_no_bin() {
    [ "$HAS_BIN" -eq 0 ] && return 1
    record "$1" 1 "$BIN $2" >/dev/null
}

# ok_case <section> <args...>: expected output computed by ref.py
ok_case() {
    local sec=$1
    shift
    skip_if_no_bin "$sec" "$*" || {
        $REF "$@" >"$TMP/exp"
        launch "$@"
        compare_output "$sec" "$TMP/exp"
    }
}

# literal_case <section> <expected text> <args...>: expected output copied from the subject
literal_case() {
    local sec=$1
    printf '%s' "$2" >"$TMP/exp"
    shift 2
    skip_if_no_bin "$sec" "$*" || {
        launch "$@"
        compare_output "$sec" "$TMP/exp"
    }
}

# err_case <args...>: exit 84, message on stderr, nothing on stdout
err_case() {
    local sec=errors
    skip_if_no_bin "$sec" "$*" || {
        launch "$@"
        local why details=() bad=0
        why=$(abnormal)
        [ -n "$why" ] && { details+=("$why"); bad=1; }
        [ "$RC" -ne 84 ] && [ -z "$why" ] && { details+=("${R}exit $RC${N} ${D}(expected 84)${N}"); bad=1; }
        [ -s "$TMP/err" ] || { details+=("${R}nothing on stderr${N}"); bad=1; }
        if [ -s "$TMP/out" ]; then
            details+=("${R}unexpected stdout:${N}")
            mapfile -t -O "${#details[@]}" details < <(head -n 5 "$TMP/out" | cat -e | sed 's/^/  /')
            bad=1
        fi
        [ "$bad" -eq 0 ] && mapfile -t details < <(echo "${D}exit 84${N}"; stderr_lines)
        record "$sec" "$bad" "$LABEL" "${details[@]}"
    }
}

# lenient_case <args...>: the subject does not settle it. Must end cleanly (0 or 84) and never print nan/inf.
lenient_case() {
    local sec=undefined
    skip_if_no_bin "$sec" "$*" || {
        launch "$@"
        local why details=() bad=0
        why=$(abnormal)
        [ -n "$why" ] && { details+=("$why"); bad=1; }
        { [ "$RC" -eq 0 ] || [ "$RC" -eq 84 ] || [ -n "$why" ]; } || { details+=("${R}exit $RC${N} ${D}(expected 0 or 84)${N}"); bad=1; }
        grep -qiE '\b-?(nan|inf)\b' "$TMP/out" && { details+=("${R}nan/inf printed${N}"); bad=1; }
        mapfile -t -O "${#details[@]}" details < <(echo "${D}exit $RC${N}"; show "${D}" "$TMP/out" | sed "s/\$/${N}/"; stderr_lines)
        record "$sec" "$bad" "$LABEL" "${details[@]}"
    }
}

# ------------------------------------------------------------------ repository
section "repository"
run ls -la --color=always
PREBUILT=1
[ -f 101pong ] && PREBUILT=0
junk=$(find . -path ./.git -prune -o \( -name '*.o' -o -name '*.a' -o -name '*.so' -o -name '*.pyc' -o -name '__pycache__' \
    -o -name 'a.out' -o -name '*~' -o -name '#*#' -o -name 'vgcore.*' \) -print)
record "repo" "$([ -z "$junk" ]; echo $?)" "no useless files committed (*.o, a.out, __pycache__, *~ …)" ${junk:+"${D}found: $(echo $junk)${N}"}
if [ "$PREBUILT" -eq 0 ]; then
    is_elf=1
    [ "$(head -c 4 101pong | tail -c 3)" = "ELF" ] && is_elf=0
    record "repo" "$([ "$is_elf" -ne 0 ]; echo $?)" "committed 101pong is a script, not a compiled binary"
fi

# ------------------------------------------------------------------ Makefile (only "when necessary")
section "Makefile"
if [ -f Makefile ] || [ -f makefile ]; then
    run make fclean
    run make
    record "Makefile" "$([ -f "$BIN" ]; echo $?)" "make → $BIN"
    before=$(stat -c %Y "$BIN" 2>/dev/null)
    sleep 1
    run make
    record "Makefile" "$([ -n "$before" ] && [ "$(stat -c %Y "$BIN" 2>/dev/null)" = "$before" ]; echo $?)" "no relink on a second make"
    run make clean
    objs=$(find . -path ./.git -prune -o -name '*.o' -print)
    record "Makefile" "$([ -z "$objs" ] && [ -f "$BIN" ]; echo $?)" "make clean → *.o removed, $BIN kept"
    run make fclean
    if [ "$PREBUILT" -ne 0 ]; then
        record "Makefile" "$([ ! -e "$BIN" ]; echo $?)" "make fclean → $BIN removed"
    fi
    run make re
    record "Makefile" "$([ -f "$BIN" ]; echo $?)" "make re → $BIN rebuilt"
elif [ "$PREBUILT" -eq 0 ]; then
    echo "  ${D}no Makefile: allowed, 101pong is committed directly${N}"
else
    record "Makefile" 1 "Makefile or committed 101pong script" "${R}neither one is present${N}"
fi

# ------------------------------------------------------------------ program
section "program"
if [ ! -f "$BIN" ]; then
    record "program" 1 "$BIN exists" "${R}every test below fails${N}"
    HAS_BIN=1
else
    record "program" 0 "$BIN exists"
    x_ok=$([ -x "$BIN" ]; echo $?)
    record "program" "$x_ok" "$BIN is executable"
    HAS_BIN=$x_ok

    # A missing interpreter comes from the sandbox image, not necessarily from the student.
    if [ "$(head -c 2 "$BIN")" = "#!" ]; then
        read -r -a shebang < <(head -n 1 "$BIN" | cut -c3-)
        interp=${shebang[0]}
        [ "$(basename "$interp")" = "env" ] && interp=${shebang[1]}
        if ! command -v "$interp" >/dev/null; then
            printf '  %s⚠ interpreter "%s" is not installed in the sandbox image: add it to the image before grading this student%s\n' "$Y" "$interp" "$N"
        fi
    elif [ "$(head -c 4 "$BIN" | tail -c 3)" != "ELF" ]; then
        record "program" 1 "script starts with a shebang (#!)" "${D}$(head -n 1 "$BIN" | cut -c1-60)${N}"
    fi
fi

# ------------------------------------------------------------------ usage
section "-h"
USAGE='USAGE
    ./101pong x0 y0 z0 x1 y1 z1 n

DESCRIPTION
    x0 ball abscissa at time t - 1
    y0 ball ordinate at time t - 1
    z0 ball altitude at time t - 1
    x1 ball abscissa at time t
    y1 ball ordinate at time t
    z1 ball altitude at time t
    n time shift (greater than or equal to zero, integer)'
if skip_if_no_bin "-h" "-h"; then :; else
    launch -h
    # Blank lines and trailing spaces cannot be read reliably from the subject: not judged.
    if [ "$RC" -eq 0 ] && cmp -s <(echo "$USAGE" | grep -v '^$') <(sed 's/[ \t]*$//' "$TMP/out" | grep -v '^$'); then
        mapfile -t details < <(show "${D}" "$TMP/out" | sed "s/\$/${N}/")
        record "-h" 0 "$LABEL" "${details[@]}"
    else
        mapfile -t details < <(echo "${D}exit $RC (expected 0); expected text:${N}"; echo "$USAGE" | sed 's/^/  /'; echo "${R}got:${N}"; show "  " "$TMP/out"; stderr_lines)
        record "-h" 1 "$LABEL" "${details[@]}"
    fi
fi

# ------------------------------------------------------------------ subject examples (literal expected output)
section "subject examples"
literal_case "subject" "The velocity vector of the ball is:
(6.00, 6.00, -7.00)
At time t + 4, ball coordinates will be:
(31.00, 33.00, -30.00)
The ball won't reach the paddle.
" 1 3 5 7 9 -2 4
literal_case "subject" "The velocity vector of the ball is:
(-8.10, 6.00, -3.00)
At time t + 4, ball coordinates will be:
(-39.40, 33.00, -10.00)
The incidence angle is:
16.57 degrees
" 1.1 3 5 -7 9 2 4

# ------------------------------------------------------------------ paddle hit
section "paddle: ball reaches z = 0"
ok_case hit  0 0 5   0 0 3   1        # straight down: 90 degrees
ok_case hit  0 0 -5  0 0 -3  1        # straight up from below: 90 degrees, never negative
ok_case hit  0 0 2   1 0 1   0        # exactly 45 degrees
ok_case hit  0 0 8   3 4 3   0        # 3-4-5 style angle
ok_case hit  0 0 -8  -3 -4 -3 2       # same, from below
ok_case hit  0 0 1   1000 0 0.5 0     # grazing, angle close to 0
ok_case hit  0 0 1   -1000 2000 0.99 0
ok_case hit  2.5 -3.5 10 3 -3 9 7
ok_case hit  1 1 5   2 2 0   3        # z1 = 0, reached exactly at t = 0
ok_case hit  1 1 -5  2 2 0   3        # z1 = 0, from below
ok_case hit  1 1 0.01 1 2 0  0        # z1 = 0, shallow

section "paddle: ball never reaches z = 0"
ok_case miss 0 0 3   0 0 5   1        # moving away, above
ok_case miss 0 0 -3  0 0 -5  1        # moving away, below
ok_case miss 0 0 -1  0 0 1   4        # crossed z = 0 before t
ok_case miss 0 0 1   0 0 -1  4        # crossed z = 0 before t, downwards
ok_case miss 0 0 0   0 0 5   2        # left z = 0 at t - 1
ok_case miss 0 0 0   0 0 -5  2        # same, downwards
ok_case miss 1 2 5   3 4 5   3        # parallel to the paddle: no division by zero
ok_case miss 1 2 -5  3 4 -5  3        # parallel, below
ok_case miss 1 1 1   1 1 1   0        # motionless above the paddle: null vector
ok_case miss 1 1 -1  1 1 -1  9        # motionless below

# ------------------------------------------------------------------ values and precision
section "values"
ok_case values 0 0 0.5 0 0 0.25 0     # n = 0: position is the second point
ok_case values 1 2 3 4 5 6 0
ok_case values -1 -2 -3 -4 -5 -6 3    # only negatives
ok_case values 0.001 0.002 5 0.004 0.008 4 2
ok_case values 1 2 3 4 5 6 1000000    # large n
ok_case values 1 2 -3 4 5 -2 999999999
ok_case values 100000 200000 300000 100001 200002 299997 100000
ok_case values 007 08 09 1 2 3 5      # leading zeros are still numbers

section "float precision"
ok_case precision 0.1 0.2 0.3 0.4 0.5 0.1 3
ok_case precision 1000000.1 2 3 1000000.3 4 2 1      # wrong with a 32-bit float
ok_case precision 12345678.12 1 9 12345678.45 2 8 0  # wrong with a 32-bit float
ok_case precision 123456789012 1 9 123456789013 2 8 1
ok_case precision 0.7 0.1 0.2 0.1 0.7 0.1 10

section "random coordinates (fixed seed)"
while read -r -a args; do
    ok_case random "${args[@]}"
done < <($REF --random 30)

# ------------------------------------------------------------------ errors
section "errors: exit 84, message on stderr, empty stdout"
err_case                                  # no argument
err_case 1
err_case 1 2 3
err_case 1 2 3 4 5 6                      # one missing
err_case 1 2 3 4 5 6 7 8                  # one too many
err_case 1 2 3 4 5 6 7 8 9 10 11 12 13 14

err_case a 3 5 7 9 -2 4                   # letters, every position
err_case 1 a 5 7 9 -2 4
err_case 1 3 a 7 9 -2 4
err_case 1 3 5 a 9 -2 4
err_case 1 3 5 7 a -2 4
err_case 1 3 5 7 9 a 4
err_case 1 3 5 7 9 -2 a

err_case 1 3 5 7 9 -2 -1                  # invalid n
err_case 1 3 5 7 9 -2 -100
err_case 1 3 5 7 9 -2 2.5
err_case 1 3 5 7 9 -2 0.1
err_case 1 3 5 7 9 -2 ""
err_case 1 3 5 7 9 -2 4a
err_case 1 3 5 7 9 -2 a4
err_case 1 3 5 7 9 -2 nan
err_case 1 3 5 7 9 -2 inf

err_case "" 3 5 7 9 -2 4                  # malformed numbers
err_case " " 3 5 7 9 -2 4
err_case 1 3 5 "" 9 -2 4
err_case 1 3 5 7 9 "" 4
err_case 12abc 3 5 7 9 -2 4
err_case abc12 3 5 7 9 -2 4
err_case 1.2.3 3 5 7 9 -2 4
err_case 1,5 3 5 7 9 -2 4
err_case "1 2" 3 5 7 9 -2 4
err_case . 3 5 7 9 -2 4
err_case - 3 5 7 9 -2 4
err_case -- 3 5 7 9 -2 4
err_case --5 3 5 7 9 -2 4
err_case +-5 3 5 7 9 -2 4
err_case 1e 3 5 7 9 -2 4

err_case nan 3 5 7 9 -2 4                 # accepted by atof / float(): not coordinates
err_case 1 nan 5 7 9 -2 4
err_case 1 3 nan 7 9 -2 4
err_case 1 3 5 inf 9 -2 4
err_case 1 3 5 7 -inf -2 4
err_case 1 3 5 7 9 infinity 4

# ------------------------------------------------------------------ undefined by the subject
section "not defined by the subject: must exit cleanly (0 or 84), no nan/inf"
lenient_case 0 0 0 0 0 0 0                # motionless on the paddle: null vector
lenient_case 1 1 0 1 1 0 3
lenient_case 0 0 0 1 1 0 2                # rolling inside the plane
lenient_case 1e3 3 5 7 9 -2 4             # number syntaxes
lenient_case +5 3 5 7 9 -2 4
lenient_case .5 3 5 7 9 -2 4
lenient_case 5. 3 5 7 9 -2 4
lenient_case 0x10 3 5 7 9 -2 4
lenient_case 1_000 3 5 7 9 -2 4
lenient_case 1 3 5 7 9 -2 4.0             # n written differently
lenient_case 1 3 5 7 9 -2 +4
lenient_case 1 3 5 7 9 -2 -0
lenient_case 1e999 3 5 7 9 -2 4           # out of range
lenient_case 1 3 5 7 9 -2 99999999999999999999
lenient_case -h 1                         # -h with other arguments
lenient_case --help
lenient_case -x

summary
