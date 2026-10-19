#!/usr/bin/env bash
# Agora test set template.
# Runs inside the sandbox: current dir = /work (student repo), test files in /tests (read-only).
# Writes go to /work or /tmp. No network. Print "AGORA_SCORE: x/y" to fill the score column.

# ------------------------------------------------------------------ config
# Student files compiled together with /tests/main.c. Leave empty to take every
# .c file of the repo that does not define its own main().
SOURCES=(my_strlen.c my_revstr.c)
CFLAGS=(-Wall -Wextra -I/work/include -I/work)
BIN=/tmp/agora_test
TEST_TIMEOUT=5

# ------------------------------------------------------------------ helpers
G=$'\e[1;32m' R=$'\e[1;31m' Y=$'\e[1;33m' B=$'\e[1;34m' D=$'\e[2m' N=$'\e[0m'
PASS=0 TOTAL=0

section() { printf '\n%s== %s ==%s\n' "$B" "$1" "$N"; }

# check <name> <expected stdout> <cmd...>
check() {
    local name=$1 expected=$2 got rc
    shift 2
    TOTAL=$((TOTAL + 1))
    got=$(timeout "$TEST_TIMEOUT" "$@" 2>&1)
    rc=$?
    if [ $rc -eq 124 ]; then
        printf '  %s[TIMEOUT]%s %s\n' "$R" "$N" "$name"
    elif [ $rc -ge 128 ]; then
        printf '  %s[CRASH]%s   %s %s(signal %d)%s\n' "$R" "$N" "$name" "$D" $((rc - 128)) "$N"
    elif [ "$got" == "$expected" ]; then
        PASS=$((PASS + 1))
        printf '  %s[OK]%s      %s\n' "$G" "$N" "$name"
    else
        printf '  %s[KO]%s      %s\n' "$R" "$N" "$name"
        printf '            %sexpected:%s %q\n' "$D" "$N" "$expected"
        printf '            %sgot:     %s %q\n' "$D" "$N" "$got"
    fi
}

finish() {
    local color=$R
    [ "$PASS" -eq "$TOTAL" ] && color=$G
    printf '\n%sAGORA_SCORE: %d/%d%s\n' "$color" "$PASS" "$TOTAL" "$N"
    [ "$PASS" -eq "$TOTAL" ]
    exit
}

# ------------------------------------------------------------------ build
section "repository"
ls -la --color=always

section "compilation"
if [ ${#SOURCES[@]} -eq 0 ]; then
    mapfile -t SOURCES < <(find . -name '*.c' -not -path './tests/*' -exec grep -L 'main[[:space:]]*(' {} +)
fi
missing=0
for f in "${SOURCES[@]}"; do
    [ -f "$f" ] || { printf '  %smissing file:%s %s\n' "$R" "$N" "$f"; missing=1; }
done
echo "${D}gcc ${CFLAGS[*]} /tests/main.c ${SOURCES[*]} -o $BIN${N}"
if [ $missing -ne 0 ] || ! gcc "${CFLAGS[@]}" -fdiagnostics-color=always /tests/main.c "${SOURCES[@]}" -o "$BIN"; then
    printf '%scompilation failed%s\n' "$R" "$N"
    TOTAL=1
    finish
fi
printf '%scompilation ok%s\n' "$G" "$N"

# ------------------------------------------------------------------ tests
# One line per test: name, expected output, command. main.c dispatches on argv[1].
section "my_strlen"
check "empty string"  "0"  "$BIN" strlen ""
check "hello"         "5"  "$BIN" strlen "hello"
check "with spaces"   "11" "$BIN" strlen "hello world"

section "my_revstr"
check "empty string"  ""       "$BIN" revstr ""
check "one char"      "a"      "$BIN" revstr "a"
check "word"          "olleh"  "$BIN" revstr "hello"

finish
