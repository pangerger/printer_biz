/* Offline candidates for print quality comparisons. Does not change the driver. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

static long dimension(const char *text) {
    char *end;errno=0;long value=strtol(text,&end,10);
    return errno || end==text || *end ? -1 : value;
}

int main(int argc,char **argv) {
    if (argc!=4) return 2;
    long w=dimension(argv[1]),h=dimension(argv[2]);
    const char *mode=argv[3];
    int fs=!strcmp(mode,"diffusion"),ordered=!strcmp(mode,"ordered");
    int threshold=!strcmp(mode,"strong") ? 160 : 128;
    if (w<1 || h<1 || w>20000 || h>20000 || w*h>100000000 ||
        (!fs && !ordered && strcmp(mode,"text") && strcmp(mode,"strong"))) return 2;
    size_t size=(size_t)w*h,stride=((size_t)w+7)/8;
    unsigned char *gray=malloc(size),*bits=calloc(stride,(size_t)h);
    float *current=calloc((size_t)w+2,sizeof(float)),*next=calloc((size_t)w+2,sizeof(float));
    if (!gray || !bits || !current || !next) {free(gray);free(bits);free(current);free(next);return 3;}
    if (fread(gray,1,size,stdin)!=size || fgetc(stdin)!=EOF || ferror(stdin)) {
        free(gray);free(bits);free(current);free(next);return 2;
    }
    const int bayer[4][4]={{0,8,2,10},{12,4,14,6},{3,11,1,9},{15,7,13,5}};
    for (long y=0;y<h;++y) {
        int reverse=fs && (y&1);
        for (long i=0;i<w;++i) {
            long x=reverse ? w-1-i : i;
            int black;
            if (fs) {
                float v=gray[(size_t)y*w+x]+current[x+1];
                if (v<0) v=0;if (v>255) v=255;
                black=v<128;
                float error=v-(black ? 0 : 255);
                if (reverse) {
                    current[x]+=error*7/16;next[x+2]+=error*3/16;
                    next[x+1]+=error*5/16;next[x]+=error/16;
                } else {
                    current[x+2]+=error*7/16;next[x]+=error*3/16;
                    next[x+1]+=error*5/16;next[x+2]+=error/16;
                }
            } else {
                int cutoff=ordered ? bayer[y%4][x%4]*16+8 : threshold;
                black=gray[(size_t)y*w+x]<cutoff;
            }
            if (black) bits[(size_t)y*stride+x/8]|=128>>(x%8);
        }
        if (fs) {float *swap=current;current=next;next=swap;memset(next,0,((size_t)w+2)*sizeof(float));}
    }
    int ok=printf("P4\n%ld %ld\n",w,h)>0 && fwrite(bits,1,stride*h,stdout)==stride*(size_t)h && !fflush(stdout);
    free(gray);free(bits);free(current);free(next);return ok ? 0 : 4;
}
