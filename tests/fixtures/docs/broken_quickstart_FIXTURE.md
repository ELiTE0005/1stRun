<!-- FIXTURE: hand-written known-broken quickstart for FirstRun tests. Not real docs. -->
# Demo Quickstart

This guide sets up a small Python project. Follow each step in order.
Step 3 pins a version of chromadb that does not exist on PyPI.

## 1. Upgrade pip

```bash
pip install --upgrade pip
```

## 2. Install requests

```bash
pip install requests==2.31.0
```

## 3. Install chromadb

```bash
pip install chromadb==0.3
```

## 4. Check the install

```bash
python -c "import requests; print(requests.__version__)"
```
