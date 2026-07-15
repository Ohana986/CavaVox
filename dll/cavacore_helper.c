#include "cavacore.h"

/* Safe getter functions for ctypes - avoids struct padding issues */
int cavacore_get_number_of_bars(struct cava_plan *plan) {
    return plan->number_of_bars;
}
int cavacore_get_audio_channels(struct cava_plan *plan) {
    return plan->audio_channels;
}
int cavacore_get_status(struct cava_plan *plan) {
    return plan->status;
}
const char *cavacore_get_error(struct cava_plan *plan) {
    return plan->error_message;
}
float cavacore_get_cut_off_frequency(struct cava_plan *plan, int index) {
    return plan->cut_off_frequency[index];
}
int cavacore_get_bass_cut_off_bar(struct cava_plan *plan) {
    return plan->bass_cut_off_bar;
}
int cavacore_get_input_buffer_size(struct cava_plan *plan) {
    return plan->input_buffer_size;
}
int cavacore_get_rate(struct cava_plan *plan) {
    return plan->rate;
}
