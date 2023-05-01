#!/bin/bash

doc="$1"
doc="${doc-:'{"on":true,"v":true}'}"

curl \
    --include \
    --header "Connection: Upgrade" \
    --header "Upgrade: websocket" \
    --header "Host: wled-1.local:80" \
    --header "Sec-WebSocket-Key: SGVsbG8sIHdvcmxkIQ==" \
    --header "Sec-WebSocket-Version: 13" \
    -d "${doc}" \
    "http://wled-1.local:80/ws"

