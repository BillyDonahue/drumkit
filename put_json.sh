#!/bin/bash

doc="$1"
doc="${doc-:'{"on":true,"v":true}'}"

curl \
    -X POST \
    "http://wled-1.local/json/state" \
    -d "${doc}" \
    -H "Content-Type: application/json"
