/* Exercise the actual native halftone function with the original gray sample. */
#include "raster.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc,char **argv) {
    if (argc!=4) return 2;
    size_t w=strtoul(argv[1],NULL,10),h=strtoul(argv[2],NULL,10);
    if (!w || w%8 || !h || w>20000 || h>20000) return 2;
    unsigned char *gray=malloc(w*h);
    if (!gray) return 3;
    if (fread(gray,1,w*h,stdin)!=w*h || fgetc(stdin)!=EOF) {free(gray);return 2;}
    unsigned char *bits=bizhub_halftone(gray,w,w,h,!strcmp(argv[3],"Photo"));
    free(gray);
    if (!bits) return 3;
    int ok=printf("P4\n%zu %zu\n",w,h)>0 && fwrite(bits,1,w*h/8,stdout)==w*h/8 && !fflush(stdout);
    free(bits);return ok ? 0 : 4;
}
