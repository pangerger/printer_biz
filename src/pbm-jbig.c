/* SPDX-License-Identifier: GPL-2.0-or-later
 * One-plane PBM -> JBIG encoder using the external JBIG-KIT sources.
 */
#include "jbig.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int failed = 0;
static void output(unsigned char *data, size_t size, void *unused) {
    (void)unused;
    if (fwrite(data, 1, size, stdout) != size) failed = 1;
}

int main(void) {
    char magic[16], dimensions[128], extra;
    unsigned long width = 0, height = 0;
    if (!fgets(magic, sizeof(magic), stdin) || strcmp(magic, "P4\n") ||
        !fgets(dimensions, sizeof(dimensions), stdin) ||
        sscanf(dimensions, "%lu %lu %c", &width, &height, &extra) != 2 ||
        width == 0 || height == 0 || width > 20000 || height > 20000 ||
        width * height > 100000000) {
        fprintf(stderr, "Expected bounded P4 output from pdf-raster\n"); return 2;
    }
    size_t size = ((width+7)/8)*height;
    unsigned char *pixels = malloc(size);
    if (!pixels) return 3;
    if (fread(pixels, 1, size, stdin) != size || fgetc(stdin) != EOF) {
        fprintf(stderr, "Truncated raster or unexpected trailing data\n"); free(pixels); return 2;
    }
    if (width % 8) {
        size_t stride = (width+7)/8;
        unsigned char mask = (unsigned char)(255 << (8-width%8));
        for (size_t y = 0; y < height; ++y) pixels[y*stride+stride-1] &= mask;
    }
    struct jbg_enc_state state;
    jbg_enc_init(&state, width, height, 1, &pixels, output, NULL);
    // Matches BIH produced by the official module in offline emulation:
    // one resolution layer, one stripe, two-line template, TP, no ATMOVE.
    jbg_enc_options(&state, JBG_ILEAVE | JBG_SMID, JBG_LRLTWO | JBG_TPBON, height, 0, 0);
    jbg_enc_out(&state);
    jbg_enc_free(&state);
    free(pixels);
    if (fflush(stdout)) failed = 1;
    return failed ? 4 : 0;
}
