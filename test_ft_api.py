# -*- coding: utf-8 -*-
"""
Connect to existing Chrome via Chrome DevTools Protocol (CDP) or dump full rendered text
"""
import sys
import json
from curl_cffi import requests
from bs4 import BeautifulSoup

# Let's test checking FT user status API endpoint using the cookies
HEADERS = {
    "cookie": """FTClientSessionId=376442ae-15e9-472d-9a65-afe408520d14; spoor-id=376442ae-15e9-472d-9a65-afe408520d14; FTSession_s=048eR9BAm0sf05srsskIStAL0wAAAaBCT2PAw8I.MEMCH22X2Cl3SzzPMzdImtsb8tEiPejrsODVMliGkR67YpoCIEKUEzCC2UJA0DPdsc57tYXWhXcuVOYRUHb1Kj4wi6Jx; next-edition=international;""",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "accept": "application/json, text/plain, */*",
}

endpoints = [
    "https://www.ft.com/__origami/service/session-service/v2/session",
    "https://www.ft.com/myft/api/following",
    "https://www.ft.com/session-token",
]

for ep in endpoints:
    try:
        r = requests.get(ep, headers=HEADERS, impersonate="chrome124", timeout=10)
        print(f"Endpoint: {ep} -> Status: {r.status_code}")
        print("Body preview:", r.text[:200])
    except Exception as e:
        print(f"Endpoint error {ep}: {e}")
