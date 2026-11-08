CC = clang
CFLAGS = -std=c11 -O2 -Wall -Wextra -Werror

.PHONY: all
all: build/pdf-raster build/usb-status

JBIG_SOURCE ?= /Volumes/W/Downloads/autoChrome/bizhub185/jbigkit-source

build/pbm-jbig: src/pbm-jbig.c
	python3 -c 'import bizhub; bizhub.external_directory()'
	mkdir -p build
	$(CC) -std=c11 -O2 -I"$(JBIG_SOURCE)" $< "$(JBIG_SOURCE)/jbig.c" "$(JBIG_SOURCE)/jbig_ar.c" -o $@

build/bizhub185-filter: src/cups-filter.c src/raster.c src/raster.h
	python3 -c 'import bizhub; bizhub.external_directory()'
	mkdir -p build
	$(CC) -std=c11 -O2 -Wall -Wextra -I"$(JBIG_SOURCE)" src/cups-filter.c src/raster.c "$(JBIG_SOURCE)/jbig.c" "$(JBIG_SOURCE)/jbig_ar.c" -framework CoreGraphics -framework CoreFoundation -lcups -o $@

build/pdf-raster: src/pdf-raster.c
	mkdir -p build
	$(CC) $(CFLAGS) $< -framework CoreGraphics -framework CoreFoundation -o $@

build/usb-status: src/usb-status.c
	mkdir -p build
	$(CC) $(CFLAGS) $< -framework IOKit -framework CoreFoundation -o $@

.PHONY: test
test: build/pdf-raster
	python3 -m unittest discover -s tests -p test_pipeline.py -v

.PHONY: test-native
test-native: build/bizhub185-filter build/pbm-jbig build/decode-jbig
	python3 -m unittest discover -s tests -p test_native.py -v

build/decode-jbig: tests/decode-jbig.c
	python3 -c 'import bizhub; bizhub.external_directory()'
	$(CC) -std=c11 -O2 -I"$(JBIG_SOURCE)" $< "$(JBIG_SOURCE)/jbig.c" "$(JBIG_SOURCE)/jbig_ar.c" -o $@

build/quality-halftone: tools/quality-halftone.c
	mkdir -p build
	$(CC) $(CFLAGS) $< -o $@

build/native-halftone: tests/native-halftone.c src/raster.c src/raster.h
	mkdir -p build
	$(CC) $(CFLAGS) -Isrc tests/native-halftone.c src/raster.c -framework CoreGraphics -framework CoreFoundation -o $@
