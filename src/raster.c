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

unsigned char *bizhub_raster_page(CGPDFPageRef pdf, size_t *width, size_t *height, int photo, int landscape) {
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
    CGContextScaleCTM(context,600/72.0,600/72.0);
    CGRect destination=CGRectMake(0,0,canvas_w,canvas_h);
    // Explicit landscape on an unrotated portrait PDF fits its upright
    // content onto a landscape canvas before that canvas is fed sideways.
    if (!wide && turn) {
        double logical_w=canvas_h,logical_h=canvas_w;
        if (turn==90) {
            CGContextTranslateCTM(context,canvas_w,0);
            CGContextRotateCTM(context,M_PI_2);
        } else {
            CGContextTranslateCTM(context,0,canvas_h);
            CGContextRotateCTM(context,-M_PI_2);
        }
        destination=CGRectMake(0,0,logical_w,logical_h);
        // GetDrawingTransform does not upscale small pages, which is
        // intentional here: fit the source to the selected sheet.
        CGContextConcatCTM(context,CGPDFPageGetDrawingTransform(pdf,kCGPDFCropBox,destination,0,true));
    } else {
        CGContextConcatCTM(context,CGPDFPageGetDrawingTransform(pdf,kCGPDFCropBox,destination,turn,true));
    }
    CGContextDrawPDFPage(context,pdf);
    CGContextRelease(context);
    unsigned char *packed=bizhub_halftone(gray,cw,rw,rh,photo);
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
