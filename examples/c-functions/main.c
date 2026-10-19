/*
** Agora test driver: ./agora_test <function> [args...]
** Compiled together with the student's files by tests.sh.
*/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int my_strlen(char const *str);
char *my_revstr(char *str);

static int test_strlen(int ac, char **av)
{
    printf("%d\n", my_strlen(ac > 2 ? av[2] : ""));
    return 0;
}

static int test_revstr(int ac, char **av)
{
    char *copy = strdup(ac > 2 ? av[2] : "");

    if (copy == NULL)
        return 84;
    printf("%s\n", my_revstr(copy));
    free(copy);
    return 0;
}

static const struct {
    const char *name;
    int (*fn)(int, char **);
} tests[] = {
    {"strlen", test_strlen},
    {"revstr", test_revstr},
};

int main(int ac, char **av)
{
    if (ac < 2) {
        fprintf(stderr, "usage: %s <test> [args...]\n", av[0]);
        return 84;
    }
    for (size_t i = 0; i < sizeof(tests) / sizeof(tests[0]); i++)
        if (strcmp(av[1], tests[i].name) == 0)
            return tests[i].fn(ac, av);
    fprintf(stderr, "unknown test: %s\n", av[1]);
    return 84;
}
