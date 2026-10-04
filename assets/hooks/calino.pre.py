#!/usr/bin/env python3
import os
from pathlib import Path

data_dir = Path(os.environ.get("DATA_DIR", "/mnt/containers/data"))
calino_dir = data_dir / "calino"
calino_dir.mkdir(parents=True, exist_ok=True)

caddyfile = calino_dir / "Caddyfile"
if not caddyfile.exists():
    print(f"  Creating Caddyfile at {caddyfile}...")
    content = """:8080 {
\troot * /srv

\t@options {
\t\tmethod OPTIONS
\t\tpath /caldav/*
\t}
\thandle @options {
\t\theader Access-Control-Allow-Origin *
\t\theader Access-Control-Allow-Methods "GET, POST, PUT, DELETE, PROPFIND, PROPPATCH, REPORT, OPTIONS, MKCOL, MKCALENDAR, COPY, MOVE"
\t\theader Access-Control-Allow-Headers "Authorization, Content-Type, Depth, Prefer, If-None-Match, If-Match"
\t\trespond "" 204
\t}

\thandle /caldav/* {
\t\turi strip_prefix /caldav
\t\treverse_proxy radicale:5232
\t}

\thandle {
\t\ttry_files {path} /index.html
\t\tfile_server
\t}

\trequest_body {
\t\tmax_size 10mb
\t}

\tencode gzip

\theader {
\t\tX-Frame-Options "SAMEORIGIN"
\t\tX-Content-Type-Options "nosniff"
\t\tReferrer-Policy "strict-origin-when-cross-origin"
\t\tPermissions-Policy "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()"
\t\t-Server
\t}

\t@assets path /assets/*
\theader @assets Cache-Control "public, immutable"

\t@sw path /sw.js
\theader @sw Cache-Control "no-store, no-cache, must-revalidate"
\theader @sw Service-Worker-Allowed "/"

\tlog {
\t\toutput stdout
\t\tformat console
\t}
}
"""
    caddyfile.write_text(content)
else:
    print(f"  Caddyfile already exists at {caddyfile}")
