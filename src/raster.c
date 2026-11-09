#include "raster.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

static void page_dimensions(CGPDFPageRef pdf, double *width, double *height) {
    CGRect box=CGPDFPageGetBoxRect(pdf,kCGPDFCropBox);
    int rotation=((CGPDFPageGetRotationAngle(pdf)%360)+360)%360;
    *width=box.size.width;*height=box.size.height;
    if (rotation==90 || rotation==270) { double t=*width;*width=*height;*height=t; }
}

int bizhub_a4_page(CGPDFPageRef pdf) {
    double w,h;page_dimensions(pdf,&w,&h);
    if (!isfinite(w) || !isfinite(h)) return 0;
    return (fabs(w-595.2755905512)<=0.25 && fabs(h-841.8897637795)<=0.25) ||
           (fabs(h-595.2755905512)<=0.25 && fabs(w-841.8897637795)<=0.25);
}

static int clamp_index(int index, int count) {
    if (index<0) return 0;
    return index<count ? index : count-1;
}

static unsigned char sample(const unsigned char *row, int index, int width, const unsigned char *lookup) {
    unsigned char value=row[clamp_index(index,width)];
    return lookup ? lookup[value] : value;
}

// A running box sum with fractionally weighted end taps. Fixed-point weights
// preserve 8-bit rounding between passes, as in the offline comparison.
static void box_rows(const unsigned char *src, unsigned char *dst, int width, int height,
                     double box_radius, const unsigned char *lookup) {
    const unsigned int unit=1U<<24;
    int radius=(int)box_radius;
    unsigned int inner=(unsigned int)(unit/(2*box_radius+1));
    unsigned int outer=(unit-(2*radius+1)*inner)/2;
    for (int y=0;y<height;++y) {
        unsigned int sum=0;
        for (int x=-radius;x<=radius;++x) sum+=sample(src,x,width,lookup);
        for (int x=0;x<width;++x) {
            unsigned int next=sample(src,x+radius+1,width,lookup);
            unsigned int previous=sample(src,x-radius-1,width,lookup);
            dst[x]=(unsigned char)((sum*inner+(previous+next)*outer+unit/2)>>24);
            sum+=next;
            sum-=sample(src,x-radius,width,lookup);
        }
        src+=width;
        dst+=width;
    }
}

static void transpose(const unsigned char *src, unsigned char *dst, int width, int height) {
    const int tile=32;
    for (int top=0;top<height;top+=tile) {
        int bottom=top+tile<height ? top+tile : height;
        for (int left=0;left<width;left+=tile) {
            int right=left+tile<width ? left+tile : width;
            for (int y=top;y<bottom;++y) {
                for (int x=left;x<right;++x) dst[(size_t)x*height+y]=src[(size_t)y*width+x];
            }
        }
    }
}

static void smooth(const unsigned char *src, unsigned char *dst, unsigned char *work,
                   int width, int height, double sigma, const unsigned char *lookup) {
    // Three boxes per axis with the same combined variance as the Gaussian.
    double variance=sigma*sigma/3;
    double radius=floor((sqrt(12*variance+1)-1)/2);
    double width_inner=2*radius+1;
    double fraction=width_inner*(variance-radius*(radius+1)/3)/
                    (2*((radius+1)*(radius+1)-variance));
    double box_radius=radius+fraction;
    box_rows(src,work,width,height,box_radius,lookup);
    box_rows(work,dst,width,height,box_radius,NULL);
    box_rows(dst,work,width,height,box_radius,NULL);
    transpose(work,dst,width,height);
    box_rows(dst,work,height,width,box_radius,NULL);
    box_rows(work,dst,height,width,box_radius,NULL);
    box_rows(dst,work,height,width,box_radius,NULL);
    transpose(work,dst,height,width);
}

static int natural_gray(unsigned char *gray, size_t width, size_t height) {
    // A from the portrait tone comparison. Interpolate between measured choices.
    static const unsigned char inputs[]={0,6,12,20,34,50,64,80,96,115,128,160,192,220,240,255};
    static const unsigned char outputs[]={0,40,75,100,117,127,134,141,147,154,161,182,205,226,242,255};
    unsigned char lookup[256];
    float weight[256];
    for (int value=0,segment=1;value<256;++value) {
        if (value>inputs[segment]) ++segment;
        int start=inputs[segment-1], end=inputs[segment];
        double fraction=(double)(value-start)/(end-start);
        lookup[value]=(unsigned char)lrint(outputs[segment-1]+fraction*(outputs[segment]-outputs[segment-1]));
        weight[value]=fmaxf(0,fminf(1,(115-value)/65.0f))*fminf(1,value/5.0f);
    }
    size_t count=width*height;
    unsigned char *fine=malloc(count), *local=malloc(count), *work=malloc(count);
    if (!fine || !local || !work) {
        free(fine);
        free(local);
        free(work);
        return 0;
    }
    smooth(gray,fine,work,(int)width,(int)height,1.1,lookup);
    smooth(gray,local,work,(int)width,(int)height,8,lookup);
    for (size_t i=0;i<count;++i) {
        unsigned char value=gray[i];
        float detail=fmaxf(-18,fminf(18,0.65f*(fine[i]-local[i])));
        float level=lookup[value]+detail*weight[value];
        gray[i]=(unsigned char)lrintf(fmaxf(0,fminf(255,level)));
    }
    free(fine);
    free(local);
    free(work);
    return 1;
}

static int color_span(const unsigned char *rgb) {
    int low=rgb[0], high=rgb[0];
    for (int channel=1;channel<3;++channel) {
        if (rgb[channel]<low) low=rgb[channel];
        if (rgb[channel]>high) high=rgb[channel];
    }
    return high-low;
}

static BizhubRendering automatic_rendering(const unsigned char *gray, const unsigned char *rgb,
                                           size_t width, size_t height) {
    // Dense color or sustained midtones in several small regions indicate a
    // picture. Sparse gray pixels from antialiased text don't count on their own.
    const size_t tile=96, step=8;
    unsigned int color_tiles=0, gray_tiles=0;
    for (size_t top=0;top+tile<=height;top+=tile) {
        for (size_t left=0;left+tile<=width;left+=tile) {
            unsigned int color=0, midtones=0, tones[8]={0};
            for (size_t y=top+step/2;y<top+tile;y+=step) {
                for (size_t x=left+step/2;x<left+tile;x+=step) {
                    size_t i=y*width+x;
                    unsigned char value=gray[i];
                    if (color_span(rgb+4*i)>=24) ++color;
                    if (value>=24 && value<=235) {
                        ++midtones;
                        ++tones[value/32];
                    }
                }
            }
            if (color>=32 && ++color_tiles>=2) return BIZHUB_PHOTO_DEFAULT;
            if (midtones>=32 && gray_tiles<3) {
                unsigned int bands=0;
                for (int i=0;i<8;++i) if (tones[i]>=4) ++bands;
                if (bands>=3 || midtones>=108) ++gray_tiles;
            }
        }
    }
    return gray_tiles>=3 ? BIZHUB_PHOTO_NATURAL : BIZHUB_TEXT;
}

static void color_detail_gray(unsigned char *gray, const unsigned char *rgb, size_t count) {
    for (size_t i=0;i<count;++i,rgb+=4) {
        // Encode a bounded hue difference in the gray level. Neutral pixels
        // get zero adjustment, including the white page and black lettering.
        int shift=(5*(rgb[0]-rgb[1])-(rgb[2]-rgb[1]))/24;
        if (shift>26) shift=26;
        if (shift<-26) shift=-26;
        // Blue-rich colors printed too dark in the paper trial. Give them a
        // bounded lift so violet and cyan remain distinguishable on paper.
        int blue_over_red=rgb[2]-rgb[0];
        if (blue_over_red>0) {
            int blue_over_green=rgb[2]-rgb[1];
            int lift=blue_over_red/3;
            if (blue_over_green>0) lift+=blue_over_green/5;
            shift+=lift>44 ? 44 : lift;
        }
        int level=gray[i]+shift;
        gray[i]=(unsigned char)(level<0 ? 0 : level>255 ? 255 : level);
    }
}

static void draw_page(CGContextRef context, CGPDFPageRef pdf, double width, double height, int wide, int turn) {
    CGContextScaleCTM(context,600/72.0,600/72.0);
    CGRect destination=CGRectMake(0,0,width,height);
    // Explicit landscape fits a portrait source onto the logical landscape
    // canvas before rotating it once into the physical portrait sheet.
    if (!wide && turn) {
        if (turn==90) {
            CGContextTranslateCTM(context,width,0);
            CGContextRotateCTM(context,M_PI_2);
        } else {
            CGContextTranslateCTM(context,0,height);
            CGContextRotateCTM(context,-M_PI_2);
        }
        destination=CGRectMake(0,0,height,width);
        turn=0;
    }
    CGContextConcatCTM(context,CGPDFPageGetDrawingTransform(pdf,kCGPDFCropBox,destination,turn,true));
    CGContextDrawPDFPage(context,pdf);
}

unsigned char *bizhub_raster_page(CGPDFPageRef pdf, size_t *width, size_t *height, BizhubRendering rendering, int landscape) {
    if (!bizhub_a4_page(pdf)) return NULL;
    double w,h;page_dimensions(pdf,&w,&h);
    int wide=w>h;
    if (landscape==0) landscape=wide ? 4 : 3;
    if (landscape!=3 && landscape!=4 && landscape!=5) return NULL;
    int turn=(landscape==4 ? 90 : landscape==5 ? 270 : 0);
    // The paper feed and verified PJL geometry stay portrait. Rotate the
    // logical landscape canvas into that physical sheet exactly once.
    double canvas_w=wide ? h : w,canvas_h=wide ? w : h;
    if (turn==0 && wide) {canvas_w=595.2755905512;canvas_h=841.8897637795;}
    // Verified official driver uses 4960 x 7015 for portrait A4 at 600 dpi.
    const size_t rw=4960,rh=7015,cw=(size_t)ceil(canvas_w*600/72),ch=(size_t)ceil(canvas_h*600/72);
    if (cw<rw || ch<rh || cw>rw+3 || ch>rh+3) return NULL;
    unsigned char *gray=malloc(cw*ch);
    if (!gray) return NULL;
    CGColorSpaceRef cs=CGColorSpaceCreateDeviceGray();
    CGContextRef context=CGBitmapContextCreate(gray,cw,ch,8,cw,cs,kCGImageAlphaNone);
    CGColorSpaceRelease(cs);
    if (!context) { free(gray);return NULL; }
    memset(gray,255,cw*ch);
    draw_page(context,pdf,canvas_w,canvas_h,wide,turn);
    CGContextRelease(context);
    if (rendering==BIZHUB_AUTO || rendering==BIZHUB_PHOTO_DEFAULT) {
        unsigned char *rgb=malloc(cw*ch*4);
        CGColorSpaceRef srgb=CGColorSpaceCreateWithName(kCGColorSpaceSRGB);
        CGContextRef color_context=rgb && srgb ? CGBitmapContextCreate(rgb,cw,ch,8,cw*4,srgb,
            kCGBitmapByteOrder32Big | kCGImageAlphaNoneSkipLast) : NULL;
        if (srgb) CGColorSpaceRelease(srgb);
        if (!color_context) {
            free(rgb);
            free(gray);
            return NULL;
        }
        memset(rgb,255,cw*ch*4);
        draw_page(color_context,pdf,canvas_w,canvas_h,wide,turn);
        CGContextRelease(color_context);
        if (rendering==BIZHUB_AUTO) rendering=automatic_rendering(gray,rgb,cw,ch);
        if (rendering==BIZHUB_PHOTO_DEFAULT) color_detail_gray(gray,rgb,cw*ch);
        free(rgb);
    }
    if (rendering==BIZHUB_PHOTO) {
        // Preserve the exact shadow levels of the paper-tested forest variant 3.
        // Midtones and highlights retain the C curve, and black and white stay fixed.
        static const unsigned char shadow[128]={
            0,8,16,24,32,40,48,55,61,68,75,81,88,91,94,97,
            100,103,106,109,112,114,116,118,120,122,124,126,127,129,131,133,
            135,137,139,140,140,140,141,142,142,142,143,144,144,144,145,146,
            146,146,147,148,148,148,149,150,150,150,151,152,152,152,153,154,
            154,154,154,155,155,155,155,156,156,156,156,156,157,157,157,157,
            158,158,158,158,158,159,159,159,159,159,160,160,160,160,161,161,
            161,161,161,161,162,162,162,162,162,162,163,163,163,163,163,163,
            164,164,164,164,164,164,164,165,165,165,165,165,165,166,166,166,
        };
        unsigned char tone[256];
        memcpy(tone,shadow,sizeof(shadow));
        for (size_t i=sizeof(shadow);i<sizeof(tone);++i) {
            tone[i]=(unsigned char)lround(255.0*pow(i/255.0,0.62));
        }
        for (size_t i=0;i<cw*ch;++i) gray[i]=tone[gray[i]];
    } else if (rendering==BIZHUB_PHOTO_NATURAL && !natural_gray(gray,cw,ch)) {
        free(gray);
        return NULL;
    }
    unsigned char *packed=bizhub_halftone(gray,cw,rw,rh,rendering!=BIZHUB_TEXT);
    free(gray);*width=rw;*height=rh;return packed;
}

unsigned char *bizhub_halftone(const unsigned char *gray, size_t cw, size_t rw, size_t rh, int photo) {
    if (!gray || !rw || rw%8 || !rh || cw<rw || rw>20000 || rh>20000) return NULL;
    unsigned char *packed=calloc(rw/8,rh);
    if (!packed) return NULL;
    // User-selected B: retain more antialiased text edges. D: serpentine
    // Floyd-Steinberg diffusion, matching the physically compared candidate.
    float *current=NULL,*next=NULL;
    if (photo) {
        current=calloc(rw+2,sizeof(float));next=calloc(rw+2,sizeof(float));
        if (!current || !next) {free(current);free(next);free(packed);return NULL;}
    }
    for (size_t y=0;y<rh;++y) {
        int reverse=photo && (y&1);
        for (size_t i=0;i<rw;++i) {
            size_t x=reverse ? rw-1-i : i;
            int black;
            if (photo) {
                float v=gray[y*cw+x]+current[x+1];
                if (v<0) v=0;
                if (v>255) v=255;
                black=v<128;
                float error=v-(black ? 0 : 255);
                if (reverse) {
                    current[x]+=error*7/16;next[x+2]+=error*3/16;
                    next[x+1]+=error*5/16;next[x]+=error/16;
                } else {
                    current[x+2]+=error*7/16;next[x]+=error*3/16;
                    next[x+1]+=error*5/16;next[x+2]+=error/16;
                }
            } else black=gray[y*cw+x]<160;
            if (black) packed[y*(rw/8)+x/8]|=0x80>>(x%8);
        }
        if (photo) {float *swap=current;current=next;next=swap;memset(next,0,(rw+2)*sizeof(float));}
    }
    free(current);free(next);
    return packed;
}
