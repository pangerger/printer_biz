/* SPDX-License-Identifier: GPL-2.0-or-later
 * Native PDF -> PJL/JBIG CUPS filter. Links to GPL JBIG-KIT.
 */
#include "raster.h"
#include "jbig.h"
#include <CoreFoundation/CoreFoundation.h>
#include <cups/cups.h>
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int io_error=0;
static volatile sig_atomic_t cancelled=0;
static unsigned char chunk[32768];
static size_t used=0;
static void cancel_job(int signo) { (void)signo;cancelled=1; }
static void flush_chunk(void) {
    if (!used || io_error || cancelled) return;
    if (printf("@PJL SET IMAGELEN=%zu\r\n",used)<0 || fwrite(chunk,1,used,stdout)!=used) io_error=1;
    used=0;
}
static void output(unsigned char *data,size_t length,void *unused) {
    (void)unused;
    while (length && !io_error && !cancelled) {
        size_t n=length<sizeof(chunk)-used ? length : sizeof(chunk)-used;
        memcpy(chunk+used,data,n);used+=n;data+=n;length-=n;
        if (used==sizeof(chunk)) flush_chunk();
    }
}

static CGPDFDocumentRef open_pdf(const char *filename) {
    if (filename) {
        CFURLRef url=CFURLCreateFromFileSystemRepresentation(NULL,(const UInt8 *)filename,(CFIndex)strlen(filename),false);
        CGPDFDocumentRef doc=url ? CGPDFDocumentCreateWithURL(url) : NULL;
        if (url) CFRelease(url);
        return doc;
    }
    CFMutableDataRef data=CFDataCreateMutable(NULL,0);
    if (!data) return NULL;
    unsigned char buffer[65536];size_t n;
    while ((n=fread(buffer,1,sizeof(buffer),stdin))) {
        if (CFDataGetLength(data)+(CFIndex)n>256*1024*1024) {CFRelease(data);return NULL;}
        CFDataAppendBytes(data,buffer,(CFIndex)n);
    }
    if (ferror(stdin)) {CFRelease(data);return NULL;}
    CGDataProviderRef provider=CGDataProviderCreateWithCFData(data);
    CGPDFDocumentRef doc=provider ? CGPDFDocumentCreateWithProvider(provider) : NULL;
    if (provider) CGDataProviderRelease(provider);
    CFRelease(data);return doc;
}

int main(int argc,char **argv) {
    if (argc!=6 && argc!=7) {fprintf(stderr,"ERROR: Expected CUPS filter arguments\n");return 1;}
    signal(SIGTERM,cancel_job);
    char *end;errno=0;long copies=strtol(argv[4],&end,10);
    if (errno || end==argv[4] || *end || copies<1 || copies>99) {fprintf(stderr,"ERROR: Invalid copy count\n");return 1;}
    cups_option_t *options=NULL;
    int count=cupsParseOptions(argv[5],0,&options);
    const char *size=cupsGetOption("PageSize",count,options);
    const char *duplex=cupsGetOption("Duplex",count,options);
    const char *quality=cupsGetOption("Rendering",count,options);
    int photo=quality && !strcmp(quality,"Photo");
    const char *orientation=cupsGetOption("orientation-requested",count,options);
    const char *legacy_landscape=cupsGetOption("landscape",count,options);
    int landscape=0;
    if (orientation) {
        if (!strcmp(orientation,"4")) landscape=4;
        else if (!strcmp(orientation,"5")) landscape=5;
        else if (strcmp(orientation,"3")) {
            fprintf(stderr,"ERROR: Unsupported orientation-requested\n");cupsFreeOptions(count,options);return 1;
        }
    } else if (legacy_landscape && (!strcmp(legacy_landscape,"true") || !strcmp(legacy_landscape,"yes"))) landscape=4;
    if ((size && strcmp(size,"A4")) || (duplex && strcmp(duplex,"None"))) {
        fprintf(stderr,"ERROR: This driver supports A4 simplex only\n");cupsFreeOptions(count,options);return 1;
    }
    cupsFreeOptions(count,options);
    CGPDFDocumentRef doc=open_pdf(argc==7 ? argv[6] : NULL);
    if (!doc || CGPDFDocumentIsEncrypted(doc)) {fprintf(stderr,"ERROR: Unreadable or encrypted PDF\n");if(doc)CGPDFDocumentRelease(doc);return 1;}
    size_t pages=CGPDFDocumentGetNumberOfPages(doc);
    if (!pages || pages>100) {fprintf(stderr,"ERROR: Page count outside 1..100\n");CGPDFDocumentRelease(doc);return 1;}
    // Validate all geometry before emitting a partial print job.
    for (size_t p=1;p<=pages;++p) {
        CGPDFPageRef page=CGPDFDocumentGetPage(doc,p);
        if (!bizhub_a4_page(page)) {
            fprintf(stderr,"ERROR: Page %zu must be A4\n",p);CGPDFDocumentRelease(doc);return 1;
        }
    }
    fputs("\033%-12345X@PJL\r\n@PJL SET DRIVERTYPE=XPS\r\n@PJL SET COMPRESS=JBIG\r\n"
          "@PJL SET USERNAME=Codex\r\n@PJL SET HOLD=OFF\r\n@PJL SET COVER=OFF\r\n@PJL SET SECTION=OFF\r\n",stdout);
    for (size_t p=1;p<=pages && !cancelled && !io_error;++p) {
        size_t width=0,height=0;
        unsigned char *pixels=bizhub_raster_page(CGPDFDocumentGetPage(doc,p),&width,&height,photo,landscape);
        if (!pixels) {fprintf(stderr,"ERROR: Cannot render page %zu\n",p);io_error=1;break;}
        fprintf(stderr,"PAGE: %zu %ld\n",p,copies);
        printf("@PJL SET MEDIASOURCE=AUTO\r\n@PJL SET MEDIATYPE=PLAIN\r\n"
               "@PJL SET PAGESTATUS=START\r\n@PJL SET ORIENTATION=PORTRAIT\r\n"
               "@PJL SET COPIES=%ld\r\n@PJL SET DUPLEX=OFF\r\n@PJL SET RESOLUTION=600\r\n"
               "@PJL SET PAPERWIDTH=%zu\r\n@PJL SET PAPERLENGTH=%zu\r\n@PJL SET PAPER=A4\r\n",copies,width,height);
        struct jbg_enc_state state;
        jbg_enc_init(&state,width,height,1,&pixels,output,NULL);
        jbg_enc_options(&state,JBG_ILEAVE|JBG_SMID,JBG_LRLTWO|JBG_TPBON,height,0,0);
        used=0;jbg_enc_out(&state);flush_chunk();jbg_enc_free(&state);free(pixels);
        fputs("@PJL SET PAGESTATUS=END\r\n",stdout);
    }
    if (!cancelled && !io_error) fputs("@PJL EOJ\r\n\033%-12345X\r\n",stdout);
    if (fflush(stdout) || ferror(stdout)) io_error=1;
    CGPDFDocumentRelease(doc);
    if (cancelled) {fprintf(stderr,"INFO: Print job cancelled\n");return 1;}
    return io_error ? 1 : 0;
}
