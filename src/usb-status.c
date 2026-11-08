/* USB printer diagnostics. Optional vendor-observed PJL metadata query only.
 * No reset, seize or page data writes.
 */
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOCFPlugIn.h>
#include <IOKit/IOKitLib.h>
#include <IOKit/usb/IOUSBLib.h>
#include <stdio.h>
#include <string.h>

static int property(io_service_t service, CFStringRef key) {
    CFTypeRef value = IORegistryEntryCreateCFProperty(service, key, NULL, 0);
    int result = -1;
    if (value) {
        if (CFGetTypeID(value) == CFNumberGetTypeID())
            CFNumberGetValue(value, kCFNumberIntType, &result);
        CFRelease(value);
    }
    return result;
}

static void json_string(const unsigned char *data, size_t size) {
    putchar('"');
    for (size_t i = 0; i < size; ++i) {
        unsigned char c = data[i];
        if (c == '"' || c == '\\') { putchar('\\'); putchar(c); }
        else if (c < 32 || c >= 127) printf("\\u%04x", c);
        else putchar(c);
    }
    putchar('"');
}

int main(int argc, char **argv) {
    int pjl = argc == 2 && !strcmp(argv[1], "--pjl-info-status");
    if (argc != 1 && !pjl) {
        fprintf(stderr, "usage: usb-status [--pjl-info-status]\n"); return 2;
    }
    io_iterator_t iterator = IO_OBJECT_NULL;
    kern_return_t kr = IOServiceGetMatchingServices(kIOMainPortDefault,
        IOServiceMatching("IOUSBHostInterface"), &iterator);
    if (kr != KERN_SUCCESS) return 2;
    io_service_t service;
    int found = 0, success = 0;
    while ((service = IOIteratorNext(iterator))) {
        if (property(service, CFSTR("idVendor")) != 0x132b ||
            property(service, CFSTR("idProduct")) != 0x20e7 ||
            property(service, CFSTR("bInterfaceClass")) != 7) {
            IOObjectRelease(service); continue;
        }
        found++;
        IOCFPlugInInterface **plugin = NULL;
        IOUSBInterfaceInterface300 **usb = NULL;
        SInt32 score = 0;
        kr = IOCreatePlugInInterfaceForService(service, kIOUSBInterfaceUserClientTypeID,
            kIOCFPlugInInterfaceID, &plugin, &score);
        IOObjectRelease(service);
        if (kr != KERN_SUCCESS || !plugin) {
            fprintf(stderr, "Create USB plugin failed: 0x%08x\n", kr); continue;
        }
        HRESULT hr = (*plugin)->QueryInterface(plugin,
            CFUUIDGetUUIDBytes(kIOUSBInterfaceInterfaceID300), (LPVOID *)&usb);
        IODestroyPlugInInterface(plugin);
        if (hr || !usb) { fprintf(stderr, "USB QueryInterface failed\n"); continue; }
        kr = (*usb)->USBInterfaceOpen(usb);
        if (kr != KERN_SUCCESS) {
            fprintf(stderr, "USB interface busy or denied: 0x%08x\n", kr);
            (*usb)->Release(usb); continue;
        }
        UInt8 number = 0, count = 0;
        (*usb)->GetInterfaceNumber(usb, &number);
        (*usb)->GetNumEndpoints(usb, &count);
        printf("{\"interface\":%u,\"endpoints\":[", number);
        int emitted = 0;
        UInt8 input = 0, output = 0;
        for (UInt8 pipe = 1; pipe <= count; ++pipe) {
            UInt8 direction = 0, endpoint = 0, type = 0, interval = 0;
            UInt16 packet = 0;
            kr = (*usb)->GetPipeProperties(usb, pipe, &direction, &endpoint, &type, &packet, &interval);
            if (kr == KERN_SUCCESS) {
                if (type == kUSBBulk && direction == kUSBIn) input = pipe;
                if (type == kUSBBulk && direction == kUSBOut) output = pipe;
                printf("%s{\"pipe\":%u,\"address\":%u,\"direction\":\"%s\",\"type\":%u,\"max_packet\":%u}",
                    emitted++ ? "," : "", pipe, endpoint | (direction == kUSBIn ? 128 : 0),
                    direction == kUSBIn ? "in" : "out", type, packet);
            }
        }
        UInt8 status = 0;
        IOUSBDevRequestTO request = {0};
        request.bmRequestType = 0xa1; /* IN | class | interface */
        request.bRequest = 1; /* GET_PORT_STATUS */
        request.wIndex = number;
        request.wLength = 1;
        request.pData = &status;
        request.noDataTimeout = 1000;
        request.completionTimeout = 2000;
        kr = (*usb)->ControlRequestTO(usb, 0, &request);
        printf("],\"status_request_result\":%u", kr);
        if (kr == KERN_SUCCESS && request.wLenDone == 1) {
            printf(",\"port_status\":%u,\"not_error\":%s,\"selected\":%s,\"paper_empty\":%s",
                status, status & 8 ? "true" : "false", status & 16 ? "true" : "false",
                status & 32 ? "true" : "false");
            if (!pjl) success++;
        }
        if (pjl && input && output) {
            // Exact INFO STATUS query present in official PSSX8mon.dll.
            unsigned char query[] = "\033%-12345X@PJL INFO STATUS\r\n";
            kr = (*usb)->WritePipeTO(usb, output, query, sizeof(query)-1, 1000, 2000);
            printf(",\"pjl_write_result\":%u", kr);
            if (kr == KERN_SUCCESS) {
                unsigned char response[8192];
                UInt32 length = sizeof(response);
                kr = (*usb)->ReadPipeTO(usb, input, response, &length, 1000, 2000);
                printf(",\"pjl_read_result\":%u", kr);
                if (kr == KERN_SUCCESS && length <= sizeof(response)) {
                    printf(",\"pjl_response\":"); json_string(response, length);
                    success++;
                }
            }
        }
        printf("}\n");
        (*usb)->USBInterfaceClose(usb);
        (*usb)->Release(usb);
    }
    IOObjectRelease(iterator);
    if (!found) fprintf(stderr, "bizhub 185 USB printer interface not found\n");
    return success ? 0 : 3;
}
