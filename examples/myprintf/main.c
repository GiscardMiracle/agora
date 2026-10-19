/*
** Agora - my_printf test driver.
**
** Compiled twice by tests.sh:
**   - against the student's libmy.a        -> ./agora_my
**   - with -DAGORA_REF -Dmy_printf=printf   -> ./agora_ref (reference)
**
** ./agora_xx --list  prints "section<TAB>call" for every case
** ./agora_xx <i>     runs case i: output on stdout, "ret=<r> n=<n>" on fd 3
**
** Add a case: one CASE(section, call) line. The call is displayed as-is in Agora.
*/

#include <float.h>
#include <limits.h>
#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#ifndef AGORA_REF
int my_printf(char const *format, ...);
#endif

static int n = -1;

#define CASES \
    CASE("basic",     my_printf("")) \
    CASE("basic",     my_printf("hello world")) \
    CASE("basic",     my_printf("Hello %s\n", "world !")) \
    CASE("basic",     my_printf("100%%")) \
    CASE("basic",     my_printf("%%%c%%", 'x')) \
    CASE("basic",     my_printf("line1\nline2\n")) \
    CASE("%c",        my_printf("%c", 'a')) \
    CASE("%c",        my_printf("%c%c%c", 'E', 'p', 'i')) \
    CASE("%c",        my_printf("[%c]", '\0')) \
    CASE("%s",        my_printf("%s", "Agora")) \
    CASE("%s",        my_printf("[%s]", "")) \
    CASE("%s",        my_printf("%s|%s|%s", "a", "bc", "def")) \
    CASE("%s",        my_printf("%s", (char *)NULL)) \
    CASE("%d %i",     my_printf("%d", 0)) \
    CASE("%d %i",     my_printf("%d", 42)) \
    CASE("%d %i",     my_printf("%d", -42)) \
    CASE("%d %i",     my_printf("%i", 123456)) \
    CASE("%d %i",     my_printf("%d", INT_MAX)) \
    CASE("%d %i",     my_printf("%d", INT_MIN)) \
    CASE("%d %i",     my_printf("%d %i %d", 1, -2, 3)) \
    CASE("%u",        my_printf("%u", 0u)) \
    CASE("%u",        my_printf("%u", 3000000000u)) \
    CASE("%u",        my_printf("%u", UINT_MAX)) \
    CASE("%o %x %X",  my_printf("%o", 8)) \
    CASE("%o %x %X",  my_printf("%o", 0)) \
    CASE("%o %x %X",  my_printf("%x", 255)) \
    CASE("%o %x %X",  my_printf("%X", 0xBEEF)) \
    CASE("%o %x %X",  my_printf("%x", 0)) \
    CASE("%o %x %X",  my_printf("%x", UINT_MAX)) \
    CASE("%p",        my_printf("%p", (void *)0x7ffe1234)) \
    CASE("%p",        my_printf("%p", (void *)NULL)) \
    CASE("%p",        my_printf("%p", (void *)1)) \
    CASE("mix",       my_printf("%d %s %c %x %%", 42, "str", 'z', 42)) \
    CASE("mix",       my_printf("%s is %d years old\n", "Alan", 41)) \
    CASE("flags",     my_printf("[%5d]", 42)) \
    CASE("flags",     my_printf("[%-5d]", 42)) \
    CASE("flags",     my_printf("[%05d]", 42)) \
    CASE("flags",     my_printf("[%05d]", -42)) \
    CASE("flags",     my_printf("[%+d]", 42)) \
    CASE("flags",     my_printf("[%+d]", -42)) \
    CASE("flags",     my_printf("[% d]", 42)) \
    CASE("flags",     my_printf("[% d]", -42)) \
    CASE("flags",     my_printf("[%+ d]", 42)) \
    CASE("flags",     my_printf("[%-05d]", 42)) \
    CASE("flags",     my_printf("[%+5d]", 42)) \
    CASE("flags",     my_printf("[%#o]", 8)) \
    CASE("flags",     my_printf("[%#o]", 0)) \
    CASE("flags",     my_printf("[%#x]", 255)) \
    CASE("flags",     my_printf("[%#X]", 255)) \
    CASE("flags",     my_printf("[%#x]", 0)) \
    CASE("flags",     my_printf("[%08x]", 0xabc)) \
    CASE("flags",     my_printf("[%-8x]", 0xabc)) \
    CASE("flags",     my_printf("[%10s]", "right")) \
    CASE("flags",     my_printf("[%-10s]", "left")) \
    CASE("flags",     my_printf("[%3c]", 'z')) \
    CASE("flags",     my_printf("[%-3c]", 'z')) \
    CASE("flags",     my_printf("[%20p]", (void *)0xdead)) \
    CASE("flags",     my_printf("[%-20p]", (void *)0xdead)) \
    CASE("precision", my_printf("[%.3d]", 5)) \
    CASE("precision", my_printf("[%.0d]", 0)) \
    CASE("precision", my_printf("[%5.3d]", -5)) \
    CASE("precision", my_printf("[%08.3d]", 42)) \
    CASE("precision", my_printf("[%.10u]", 42u)) \
    CASE("precision", my_printf("[%.5x]", 255)) \
    CASE("precision", my_printf("[%#.5x]", 255)) \
    CASE("precision", my_printf("[%.2s]", "hello")) \
    CASE("precision", my_printf("[%.0s]", "hello")) \
    CASE("precision", my_printf("[%10.2s]", "hello")) \
    CASE("precision", my_printf("[%-10.3s]", "hello")) \
    CASE("* width",   my_printf("[%*d]", 5, 42)) \
    CASE("* width",   my_printf("[%-*d]", 5, 42)) \
    CASE("* width",   my_printf("[%*d]", -5, 42)) \
    CASE("* width",   my_printf("[%.*d]", 4, 42)) \
    CASE("* width",   my_printf("[%.*d]", -1, 42)) \
    CASE("* width",   my_printf("[%.*s]", 3, "abcdef")) \
    CASE("* width",   my_printf("[%*.*d]", 8, 4, 42)) \
    CASE("length",    my_printf("%hhd", 300)) \
    CASE("length",    my_printf("%hhx", 0x1ff)) \
    CASE("length",    my_printf("%hd", 70000)) \
    CASE("length",    my_printf("%hu", 65537)) \
    CASE("length",    my_printf("%ld", LONG_MAX)) \
    CASE("length",    my_printf("%ld", LONG_MIN)) \
    CASE("length",    my_printf("%lu", ULONG_MAX)) \
    CASE("length",    my_printf("%lld", LLONG_MIN)) \
    CASE("length",    my_printf("%llx", 0x123456789abcdefULL)) \
    CASE("length",    my_printf("%lo", 01234567012345L)) \
    CASE("length",    my_printf("%zu", (size_t)123)) \
    CASE("length",    my_printf("%jd", (intmax_t)-1)) \
    CASE("length",    my_printf("%td", (ptrdiff_t)-7)) \
    CASE("%n",        my_printf("hello%n world", &n)) \
    CASE("%n",        my_printf("%d%s%n", 42, "abc", &n)) \
    CASE("%f %F",     my_printf("%f", 3.14)) \
    CASE("%f %F",     my_printf("%f", 0.0)) \
    CASE("%f %F",     my_printf("%f", -2.5)) \
    CASE("%f %F",     my_printf("%.2f", 3.14159)) \
    CASE("%f %F",     my_printf("%.0f", 2.5)) \
    CASE("%f %F",     my_printf("%.0f", 3.5)) \
    CASE("%f %F",     my_printf("%.3f", 0.0005)) \
    CASE("%f %F",     my_printf("[%10.3f]", 3.14159)) \
    CASE("%f %F",     my_printf("[%-10.1f]", 2.25)) \
    CASE("%f %F",     my_printf("[%+f]", 1.5)) \
    CASE("%f %F",     my_printf("[%010.2f]", -3.5)) \
    CASE("%f %F",     my_printf("[%#.0f]", 3.0)) \
    CASE("%f %F",     my_printf("%f", 1e20)) \
    CASE("%f %F",     my_printf("%Lf", (long double)1.5)) \
    CASE("%f %F",     my_printf("%f %F", INFINITY, -INFINITY)) \
    CASE("%f %F",     my_printf("%f", NAN)) \
    CASE("%e %E",     my_printf("%e", 12345.678)) \
    CASE("%e %E",     my_printf("%E", 0.000123)) \
    CASE("%e %E",     my_printf("%.2e", 9.999)) \
    CASE("%e %E",     my_printf("%e", 0.0)) \
    CASE("%e %E",     my_printf("[%15.3e]", -1234.5)) \
    CASE("%g %G",     my_printf("%g", 0.0001)) \
    CASE("%g %G",     my_printf("%g", 123456789.0)) \
    CASE("%g %G",     my_printf("%g", 100.0)) \
    CASE("%g %G",     my_printf("%G", 1e-10)) \
    CASE("%g %G",     my_printf("%#g", 1.0)) \
    CASE("%a %A",     my_printf("%a", 1.0)) \
    CASE("%a %A",     my_printf("%A", -0.5))

static void list(void)
{
#define CASE(section, call) printf("%s\t%s\n", section, #call);
    CASES
#undef CASE
}

static int run(int target)
{
    int i = 0;

#define CASE(section, call) if (i++ == target) return (call);
    CASES
#undef CASE
    return -1;
}

int main(int ac, char **av)
{
    FILE *meta;
    int ret;

    if (ac == 2 && av[1][0] == '-') {
        list();
        return 0;
    }
    if (ac != 2)
        return 84;
    ret = run(atoi(av[1]));
    fflush(stdout);
    meta = fdopen(3, "w");
    if (meta != NULL) {
        fprintf(meta, "ret=%d", ret);
        if (n != -1)
            fprintf(meta, " n=%d", n);
        fclose(meta);
    }
    return 0;
}
