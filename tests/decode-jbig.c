/* Offline test utility; not installed with the printer driver. */
#include "jbig.h"
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>

int main(void) {
    size_t capacity=65536,length=0;
    unsigned char *input=malloc(capacity);
    if (!input) return 2;
    while (!feof(stdin)) {
        if (length==capacity) {
            if (capacity>=128*1024*1024) {free(input);return 2;}
            capacity*=2;
            void *more=realloc(input,capacity);
            if (!more) {free(input);return 2;}input=more;
        }
        size_t n=fread(input+length,1,capacity-length,stdin);length+=n;
        if (ferror(stdin)) {free(input);return 2;}
    }
    if (length<20) {free(input);return 2;}
    uint32_t w=0,h=0;
    for (int i=0;i<4;++i) {w=(w<<8)|input[4+i];h=(h<<8)|input[8+i];}
    if (!w || !h || w>20000 || h>20000 || (uint64_t)w*h>100000000) {free(input);return 2;}
    struct jbg_dec_state state;jbg_dec_init(&state);jbg_dec_maxsize(&state,20000,20000);
    size_t consumed=0;
    int status=jbg_dec_in(&state,input,length,&consumed);
    if (status!=JBG_EOK || consumed!=length || jbg_dec_getplanes(&state)!=1) {
        jbg_dec_free(&state);free(input);return 3;
    }
    printf("P4\n%lu %lu\n",jbg_dec_getwidth(&state),jbg_dec_getheight(&state));
    size_t count=jbg_dec_getsize(&state);
    int ok=fwrite(jbg_dec_getimage(&state,0),1,count,stdout)==count && !fflush(stdout);
    jbg_dec_free(&state);free(input);return ok ? 0 : 4;
}
