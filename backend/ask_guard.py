"""命令行试用门卫查询 Agent（方便录 demo / 本地自测）。
用法：python ask_guard.py 今天来了几辆车
"""
import sys

import query_agent

if __name__ == "__main__":
    q = " ".join(sys.argv[1:]).strip() or input("门卫请问：")
    print(query_agent.answer(q)["reply"])
