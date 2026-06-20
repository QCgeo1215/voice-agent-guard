r"""并发登记 smoke test。

用法：
1. 先用测试配置启动后端：
   $env:DATABASE_PATH="concurrency_test.db"
   $env:NOTIFIER_PROVIDER="noop"
   .\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000

2. 另一个终端运行：
   .\.venv\Scripts\python.exe concurrency_check.py
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

import requests


BASE_URL = "http://127.0.0.1:8000"


def post_visitor(i: int, source_call_id=None):
    payload = {
        "plate_number": f"沪A{i:05d}",
        "company": "蓝色金云科技" if i % 2 == 0 else "绿腾科技",
        "phone": f"1380013{i:04d}",
        "reason": "送货" if i % 2 == 0 else "拜访",
        "source_call_id": source_call_id or f"concurrency-{i}",
    }
    started = time.perf_counter()
    resp = requests.post(f"{BASE_URL}/register_visitor", json=payload, timeout=20)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return i, resp.status_code, resp.json(), elapsed_ms


def run_batch(total=10):
    started = time.perf_counter()
    results = []
    with ThreadPoolExecutor(max_workers=total) as pool:
        futures = [pool.submit(post_visitor, i) for i in range(total)]
        for future in as_completed(futures):
            results.append(future.result())
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    ok = [r for r in results if r[1] == 200 and r[2].get("success") is True]
    print(f"unique batch: {len(ok)}/{total} success, wall={elapsed_ms}ms")
    for i, status, body, req_ms in sorted(results):
        print(
            f"  #{i:02d} status={status} success={body.get('success')} "
            f"request_id={body.get('request_id')} backend={body.get('elapsed_ms')}ms "
            f"push={body.get('push_elapsed_ms')}ms client={req_ms}ms"
        )
    assert len(ok) == total


def run_duplicate_race(total=5):
    call_id = "same-call-id-race"
    with ThreadPoolExecutor(max_workers=total) as pool:
        futures = [pool.submit(post_visitor, 100 + i, call_id) for i in range(total)]
        results = [future.result() for future in as_completed(futures)]
    ok = [r for r in results if r[1] == 200 and r[2].get("success") is True]
    print(f"duplicate race: {len(ok)}/{total} success/idempotent responses")
    for i, status, body, req_ms in sorted(results):
        print(
            f"  #{i:02d} status={status} success={body.get('success')} "
            f"message={body.get('message')} backend={body.get('elapsed_ms')}ms client={req_ms}ms"
        )
    assert len(ok) == total


if __name__ == "__main__":
    health = requests.get(f"{BASE_URL}/health", timeout=5).json()
    assert health["status"] == "ok"
    run_batch()
    run_duplicate_race()
