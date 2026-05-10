"""Reindex documents stuck at 'waiting to build' stage."""

import json
import urllib.request

BASE = "http://localhost:8080"

# Login
req = urllib.request.Request(f"{BASE}/admin/auth/login")
req.add_header("Content-Type", "application/json")
resp = json.loads(
    urllib.request.urlopen(
        req, json.dumps({"username": "admin", "password": "admin123456"}).encode()
    ).read()
)
token = resp["data"]["token"]

# Get stuck doc IDs
req = urllib.request.Request(f"{BASE}/manage/document/page/query")
req.add_header("Authorization", f"Bearer {token}")
req.add_header("Content-Type", "application/json")
data = json.loads(
    urllib.request.urlopen(req, json.dumps({"page": 1, "pageSize": 200}).encode()).read()
)
stuck = [i["documentId"] for i in data["data"]["records"] if i.get("indexStatusName") == "等待构建"]
print(f"Stuck documents: {len(stuck)}")

# Trigger reindex
for doc_id in stuck:
    req = urllib.request.Request(f"{BASE}/manage/document/index/build", method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    resp = json.loads(
        urllib.request.urlopen(req, json.dumps({"documentId": doc_id}).encode()).read()
    )
    print(f"  {doc_id}: {resp.get('message', 'OK')}")

print("Done - all stuck docs reindex triggered.")
