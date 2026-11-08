#ifndef BIZHUB_RASTER_H
#define BIZHUB_RASTER_H
#include <CoreGraphics/CoreGraphics.h>
int bizhub_a4_page(CGPDFPageRef pdf);
unsigned char *bizhub_raster_page(CGPDFPageRef pdf, size_t *width, size_t *height, int photo, int landscape);
unsigned char *bizhub_halftone(const unsigned char *gray, size_t stride, size_t width, size_t height, int photo);
#endif
