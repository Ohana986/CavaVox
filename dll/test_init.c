#include <stdio.h>
#include "../cava/cavacore.h"

int main() {
    printf("init 256@22050@5500...\n");
    struct cava_plan *p = cava_init(256, 22050, 1, 0, 0.0, 50, 5500);
    if (!p || p->status != 0) {
        printf("FAIL: %s\n", p ? p->error_message : "NULL");
        return 1;
    }
    printf("OK, bars=%d, first_freq=%.0f\n", p->number_of_bars, p->cut_off_frequency[0]);
    cava_destroy(p);
    free(p);

    printf("init 256@22050@10000...\n");
    p = cava_init(256, 22050, 1, 0, 0.0, 50, 10000);
    if (!p || p->status != 0) {
        printf("FAIL: %s\n", p ? p->error_message : "NULL");
        return 1;
    }
    printf("OK, bars=%d, last_freq=%.0f\n", p->number_of_bars, p->cut_off_frequency[p->number_of_bars]);
    cava_destroy(p);
    free(p);

    printf("All OK\n");
    return 0;
}
