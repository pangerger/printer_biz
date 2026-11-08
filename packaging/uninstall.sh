#!/bin/sh
# Run with administrator rights only when you want to remove this local driver.
set -eu
if [ "$(id -u)" -ne 0 ]; then
    echo 'Run this script using sudo from Terminal to remove the driver.' >&2
    exit 1
fi
/usr/sbin/lpadmin -x bizhub185
echo 'Removed bizhub185 printer queue. Driver files remain at /Library/Printers/bizhub185 for reinstall or manual removal.'
