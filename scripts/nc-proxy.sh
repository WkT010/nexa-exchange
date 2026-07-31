#!/bin/bash
/usr/bin/nc -X connect -x 127.0.0.1:18080 "$1" "$2"
