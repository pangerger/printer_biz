/* PDF -> PBM preprocessing only. No printer-specific wire protocol assumed. */
#include <CoreGraphics/CoreGraphics.h>
#include <CoreFoundation/CoreFoundation.h>
#include <errno.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static long number(const char *s) {
    char *end; errno = 0;
    long n = strtol(s, &end, 10);
    return errno || end == s || *end ? -1 : n;
}

int main(int argc, char **argv) {
    int count_only = argc == 3 && !strcmp(argv[2], "--pages");
    if (argc != 5 && !count_only) {
        fprintf(stderr, "usage: pdf-raster PDF PAGE DPI threshold|ordered\n");
        return 2;
    }
    long page = count_only ? 1 : number(argv[2]), dpi = count_only ? 600 : number(argv[3]);
    int ordered = !count_only && !strcmp(argv[4], "ordered");
    if (!count_only && (page < 1 || dpi < 72 || dpi > 600 ||
        (!ordered && strcmp(argv[4], "threshold")))) return 2;
    CFURLRef url = CFURLCreateFromFileSystemRepresentation(NULL,
        (const UInt8 *)argv[1], (CFIndex)strlen(argv[1]), false);
    CGPDFDocumentRef doc = url ? CGPDFDocumentCreateWithURL(url) : NULL;
    if (url) CFRelease(url);
    if (!doc || CGPDFDocumentIsEncrypted(doc) ||
        (size_t)page > CGPDFDocumentGetNumberOfPages(doc)) {
        fprintf(stderr, "PDF unreadable, encrypted, or page out of range\n");
        if (doc) CGPDFDocumentRelease(doc);
        return 3;
    }
    if (count_only) {
        printf("%zu\n", CGPDFDocumentGetNumberOfPages(doc));
        CGPDFDocumentRelease(doc); return 0;
    }
    CGPDFPageRef pdf = CGPDFDocumentGetPage(doc, (size_t)page);
    CGRect box = CGPDFPageGetBoxRect(pdf, kCGPDFCropBox);
    int rotation = ((CGPDFPageGetRotationAngle(pdf) % 360) + 360) % 360;
    double w = box.size.width, h = box.size.height;
    if (rotation == 90 || rotation == 270) { double tmp = w; w = h; h = tmp; }
    double point_width = w, point_height = h;
    w = ceil(w * dpi / 72.0); h = ceil(h * dpi / 72.0);
    if (!isfinite(w) || !isfinite(h) || w < 1 || h < 1 ||
        w > 20000 || h > 20000 || w*h > 100000000) {
        fprintf(stderr, "Page exceeds raster size limit\n");
        CGPDFDocumentRelease(doc); return 4;
    }
    size_t width = (size_t)w, height = (size_t)h;
    unsigned char *gray = malloc(width * height);
    CGColorSpaceRef cs = CGColorSpaceCreateDeviceGray();
    CGContextRef ctx = gray ? CGBitmapContextCreate(gray, width, height, 8,
        width, cs, kCGImageAlphaNone) : NULL;
    CGColorSpaceRelease(cs);
    if (!ctx) { free(gray); CGPDFDocumentRelease(doc); return 5; }
    memset(gray, 255, width * height);
    // GetDrawingTransform does not upscale small pages; apply DPI explicitly.
    CGContextScaleCTM(ctx, dpi / 72.0, dpi / 72.0);
    CGContextConcatCTM(ctx, CGPDFPageGetDrawingTransform(pdf, kCGPDFCropBox,
        CGRectMake(0, 0, point_width, point_height), 0, true));
    CGContextDrawPDFPage(ctx, pdf);
    CGContextRelease(ctx);
    static const int bayer[4][4] = {{0,8,2,10},{12,4,14,6},{3,11,1,9},{15,7,13,5}};
    size_t stride = (width + 7) / 8;
    unsigned char *row = calloc(stride, 1);
    int ok = row != NULL;
    if (ok) ok = printf("P4\n%zu %zu\n", width, height) > 0;
    for (size_t y = 0; ok && y < height; ++y) {
        memset(row, 0, stride);
        for (size_t x = 0; x < width; ++x) {
            int threshold = ordered ? bayer[y%4][x%4]*16+8 : 128;
            if (gray[y*width+x] < threshold) row[x/8] |= 0x80 >> (x%8);
        }
        ok = fwrite(row, 1, stride, stdout) == stride;
    }
    if (fflush(stdout)) ok = 0;
    free(row); free(gray); CGPDFDocumentRelease(doc);
    return ok ? 0 : 6;
}
