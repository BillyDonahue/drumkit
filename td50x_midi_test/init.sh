#!/bin/bash
PYTHON3="${PYTHON3:-python3}"
$PYTHON3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
