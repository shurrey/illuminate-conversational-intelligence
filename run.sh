#!/bin/bash
# Startup script for Lambda Web Adapter.
# LWA's /opt/bootstrap runs this instead of the Python runtime handler.
exec python3 lambda_handler.py
