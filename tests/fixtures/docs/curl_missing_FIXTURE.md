<!-- FIXTURE: hand-written quickstart where curl is missing in python:3.11-slim. Not real docs. -->
# Curl Quickstart

Two steps. The first needs curl, which the slim image does not ship.

## 1. Fetch a page

```bash
curl -fsSL https://example.com -o /dev/null
```

## 2. Finish

```bash
echo done
```
