#!/usr/bin/env bash
# Agora - my_printf test set.
# Runs in the sandbox: cwd = /work (student repo), this file + main.c in /tests (read-only).
# Every command run on the student's code is echoed with a "$" prompt.

TESTS=/tests
TMP=/tmp/agora
REF=$TMP/agora_ref
MY=$TMP/agora_my
TEST_TIMEOUT=2
ALLOWED="write malloc free"
# Calls the compiler may emit by itself: reported, not penalised.
TOLERATED="__stack_chk_fail memcpy memset memmove"

mkdir -p "$TMP"

# ------------------------------------------------------------------ display helpers
G=$'\e[1;32m' R=$'\e[1;31m' Y=$'\e[1;33m' B=$'\e[1;34m' C=$'\e[36m' M=$'\e[1;35m'
D=$'\e[2m' W=$'\e[1m' N=$'\e[0m'
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

# visible form of a file, like cat -e (newline -> $, NUL -> ^@)
vis() { cat -e "$1" | tr -d '\n'; }

summary() {
    section "summary"
    local sec color
    for sec in "${SECTIONS[@]}"; do
        color=$G
        [ "${S_PASS[$sec]}" -ne "${S_TOTAL[$sec]}" ] && color=$R
        [ "${S_PASS[$sec]}" -ne 0 ] && [ "$color" = "$R" ] && color=$Y
        printf '  %-12s %s%3d / %-3d%s\n' "$sec" "$color" "${S_PASS[$sec]}" "${S_TOTAL[$sec]}" "$N"
    done
    color=$R
    [ "$PASS" -eq "$TOTAL" ] && color=$G
    printf '\n%sAGORA_SCORE: %d/%d%s\n' "$color" "$PASS" "$TOTAL" "$N"
    [ "$PASS" -eq "$TOTAL" ]
    exit
}

# ------------------------------------------------------------------ reference build (ours)
gcc -w -DAGORA_REF -Dmy_printf=printf "$TESTS/main.c" -o "$REF" -lm || { echo "${R}agora: reference build failed${N}"; exit 2; }
mapfile -t CASES < <("$REF" --list)

# ------------------------------------------------------------------ repository
section "repository"
run ls -la --color=always
junk=$(find . -path ./.git -prune -o \( -name '*.o' -o -name '*.a' -o -name '*.gch' -o -name 'a.out' -o -name '*~' -o -name '#*#' -o -name 'vgcore.*' \) -print)
record "repo" "$([ -z "$junk" ]; echo $?)" "no useless files committed (*.o, *.a, a.out, *~ …)" ${junk:+"${D}found: $(echo $junk)${N}"}

# ------------------------------------------------------------------ Makefile
section "Makefile"
if [ ! -f Makefile ]; then
    record "Makefile" 1 "Makefile exists"
    for i in "${!CASES[@]}"; do record "${CASES[$i]%%$'\t'*}" 1 "${CASES[$i]#*$'\t'}" >/dev/null; done
    summary
fi
record "Makefile" 0 "Makefile exists"
wild=$(grep -nE '\*\.c|wildcard' Makefile)
record "Makefile" "$([ -z "$wild" ]; echo $?)" "sources listed one by one (no *.c / wildcard)" ${wild:+"${D}$wild${N}"}

run make fclean
run make all; record "Makefile" "$([ -f libmy.a ]; echo $?)" "make all → libmy.a"
before=$(stat -c %Y libmy.a 2>/dev/null)
sleep 1
run make
record "Makefile" "$([ -n "$before" ] && [ "$(stat -c %Y libmy.a 2>/dev/null)" = "$before" ]; echo $?)" "no relink on a second make"
run make clean
objs=$(find . -path ./.git -prune -o -name '*.o' -print)
record "Makefile" "$([ -z "$objs" ] && [ -f libmy.a ]; echo $?)" "make clean → *.o removed, libmy.a kept"
run make fclean
record "Makefile" "$([ ! -f libmy.a ]; echo $?)" "make fclean → libmy.a removed"
run make re
record "Makefile" "$([ -f libmy.a ]; echo $?)" "make re → libmy.a rebuilt"
if [ ! -f libmy.a ]; then
    run make libmy.a
fi
record "Makefile" "$([ -f libmy.a ]; echo $?)" "make libmy.a"

# ------------------------------------------------------------------ forbidden functions
section "forbidden functions"
if [ -f libmy.a ]; then
    printf '%s$ nm -u libmy.a%s\n' "$M" "$N"
    defined=$(nm --defined-only libmy.a 2>/dev/null | awk 'NF==3 {print $3}' | sort -u)
    used=$(nm -u libmy.a 2>/dev/null | awk '{print $NF}' | grep -v ':$' | sort -u | comm -23 - <(echo "$defined"))
    bad=() tol=()
    for f in $used; do
        if [[ " $ALLOWED " == *" $f "* ]]; then continue
        elif [[ " $TOLERATED " == *" $f "* ]]; then tol+=("$f")
        else bad+=("$f"); fi
    done
    printf '  %sexternal calls:%s %s\n' "$D" "$N" "$(echo $used)"
    [ ${#tol[@]} -ne 0 ] && printf '  %scompiler-generated (tolerated): %s%s\n' "$Y" "${tol[*]}" "$N"
    record "forbidden" "$([ ${#bad[@]} -eq 0 ]; echo $?)" "only write / malloc / free / va_*" ${bad:+"${R}forbidden: ${bad[*]}${N}"}
else
    record "forbidden" 1 "only write / malloc / free / va_*" "${D}no libmy.a${N}"
fi

# ------------------------------------------------------------------ my_printf
section "my_printf vs printf"
linked=1
if [ -f libmy.a ]; then
    run gcc -w "$TESTS/main.c" -o "$MY" -L. -lmy -lm && linked=0
fi
if [ $linked -ne 0 ]; then
    echo "  ${R}cannot link main.c with libmy.a — every my_printf test fails${N}"
fi

current=""
for i in "${!CASES[@]}"; do
    sec=${CASES[$i]%%$'\t'*}
    call=${CASES[$i]#*$'\t'}
    if [ "$sec" != "$current" ]; then
        current=$sec
        printf '\n  %s%s%s\n' "$C" "$sec" "$N"
    fi
    "$REF" "$i" >"$TMP/exp" 3>"$TMP/exp.ret" 2>/dev/null
    if [ $linked -ne 0 ]; then
        record "$sec" 1 "$call" >/dev/null
        continue
    fi
    (timeout "$TEST_TIMEOUT" "$MY" "$i" >"$TMP/got" 3>"$TMP/got.ret" 2>"$TMP/got.err"; exit $?) 2>/dev/null
    rc=$?
    exp="$(vis "$TMP/exp")" got="$(vis "$TMP/got")"
    eret=$(cat "$TMP/exp.ret") gret=$(cat "$TMP/got.ret")
    if [ $rc -eq 124 ]; then
        record "$sec" 1 "$call" "${R}TIMEOUT${N} (> ${TEST_TIMEOUT}s)"
    elif [ $rc -ge 128 ]; then
        record "$sec" 1 "$call" "${R}CRASH${N} (signal $((rc - 128))$([ $((rc - 128)) -eq 11 ] && echo ", segfault"))" \
            "${D}expected${N} \"$exp\"  ${D}$eret${N}"
    elif cmp -s "$TMP/exp" "$TMP/got" && [ "$eret" = "$gret" ]; then
        record "$sec" 0 "$call" "${D}→ \"$exp\"  $eret${N}"
    else
        record "$sec" 1 "$call" \
            "${D}expected${N} \"$exp\"  ${D}$eret${N}" \
            "${R}got     ${N} \"$got\"  $gret"
    fi
done

summary
