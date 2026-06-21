"""FastAPI 后端：接收 Voice Agent 的工具调用，登记访客并推送到微信。

两个登记入口共用同一套核心逻辑：
- POST /register_visitor       扁平 JSON，给本地 curl / 通用调用方
- POST /vapi/register_visitor  解析 Vapi 的 tool-calls 信封，返回 Vapi 要求的 results 格式
"""
import json
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from html import escape
from typing import Optional
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from config import VAPI_ASSISTANT_ID, VAPI_PUBLIC_KEY
import db
from company_registry import UnknownCompanyError, company_help_text, normalize_company
import plate_registry
import query_agent
from notifier import NotifyError, send_notification


class VisitorRequest(BaseModel):
    plate_number: str = Field(..., description="车牌号, 例如 沪A12345")
    company: str = Field(..., description="来访单位")
    phone: str = Field(..., description="手机号")
    reason: str = Field(..., description="来访事由")
    source_call_id: Optional[str] = Field(None, description="Vapi/Retell 通话ID, 用于幂等")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Voice Visitor Agent Backend", lifespan=lifespan)


def _register_core(plate_number, company, phone, reason, source_call_id):
    """登记 + 推送的核心逻辑。返回 dict，供两个端点各自封装响应。"""
    started = time.perf_counter()
    request_id = str(uuid.uuid4())[:8]

    # 幂等：同一通电话若被工具重复调用，不重复登记/推送
    existing = db.find_by_call_id(source_call_id)
    if existing:
        return {
            "success": True,
            "idempotent": True,
            "is_revisit": False,
            "request_id": request_id,
            "entry_time": existing["entry_time"],
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "push_elapsed_ms": 0,
            "push_detail": None,
        }

    entry_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 回访识别（决策 003）：insert 前按手机号查历史，本地查库几 ms，不影响延迟预算
    prior_count = db.count_visitors(phone=phone)
    last_visit = db.find_latest_by_phone(phone)
    is_revisit = prior_count > 0

    record = {
        "plate_number": plate_number,
        "company": company,
        "phone": phone,
        "reason": reason,
        "source_call_id": source_call_id,
        "entry_time": entry_time,
    }
    try:
        db.insert_visitor(record)
    except db.DuplicateCallError:
        existing = db.find_by_call_id(source_call_id)
        if existing:
            return {
                "success": True,
                "idempotent": True,
                "is_revisit": False,
                "request_id": request_id,
                "entry_time": existing["entry_time"],
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "push_elapsed_ms": 0,
                "push_detail": None,
            }
        raise

    content = _format_message(
        plate_number, company, phone, reason, entry_time,
        revisit_count=prior_count, last_visit=last_visit,
    )
    push_ok = True
    push_detail = None
    push_started = time.perf_counter()
    try:
        push_detail = send_notification("访客车辆登记", content)
    except NotifyError as e:
        push_ok = False
        push_detail = str(e)
    push_elapsed_ms = int((time.perf_counter() - push_started) * 1000)

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    # 服务端计时日志，用于 25 秒预算分析
    print(
        f"[register] request_id={request_id} plate={plate_number} "
        f"push_ok={push_ok} push_elapsed_ms={push_elapsed_ms} elapsed_ms={elapsed_ms}"
    )

    return {
        "success": push_ok,
        "idempotent": False,
        "is_revisit": is_revisit,
        "request_id": request_id,
        "entry_time": entry_time,
        "elapsed_ms": elapsed_ms,
        "push_elapsed_ms": push_elapsed_ms,
        "push_detail": push_detail,
    }


def _lookup_core(plate_number, phone=None):
    """对话内回访识别（决策 007）：先按车牌精确查，未命中再按手机号兜底。
    返回结构化历史 + 给 Agent 念的确认句；命中后由 Agent 复用历史字段登记，省去重复采集。"""
    request_id = str(uuid.uuid4())[:8]
    plate = _normalize_plate(plate_number)
    last = db.find_latest_by_plate(plate) if plate else None
    matched_by = "plate"
    visit_count = db.count_by_plate(plate) if last else 0

    if not last and phone:
        phone_n = _normalize_phone(phone)
        last = db.find_latest_by_phone(phone_n)
        if last:
            matched_by = "phone"
            visit_count = db.count_visitors(phone=phone_n)

    if not last:
        return {"found": False, "visit_count": 0, "request_id": request_id, "message": ""}

    company = last.get("company", "")
    reason = last.get("reason", "")
    date_part = (last.get("entry_time") or "")[:10]
    try:
        d = datetime.strptime(date_part, "%Y-%m-%d")
        date_say = f"{d.month}月{d.day}日"
    except ValueError:
        date_say = date_part
    return {
        "found": True,
        "matched_by": matched_by,
        "visit_count": visit_count,
        "plate_number": last.get("plate_number", ""),
        "company": company,
        "reason": reason,
        "phone": last.get("phone", ""),
        "last_date": date_part,
        "request_id": request_id,
        "message": f"您之前来过，上次{date_say}来{company}{reason}，今天还是一样吗？",
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/register_visitor")
async def register_visitor(request: Request):
    """扁平 JSON 入口（Vapi API Request / 本地 curl 用）。
    容错：清洗字段名首尾空白/换行（应对 Vapi 配置里混入 \\r\\n 的脏 key）、strip 值。
    缺字段时返回 HTTP 200 + success:false，让 Voice Agent 能据此继续追问。"""
    try:
        raw = await request.json()
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}

    cleaned = {}
    for k, v in raw.items():
        key = k.strip() if isinstance(k, str) else k
        val = v.strip() if isinstance(v, str) else v
        cleaned[key] = val

    fields = {
        "plate_number": cleaned.get("plate_number") or "",
        "company": cleaned.get("company") or "",
        "phone": cleaned.get("phone") or "",
        "reason": cleaned.get("reason") or "",
    }
    missing = [k for k, val in fields.items() if not val]
    if missing:
        return {"success": False, "message": _missing_message(missing)}

    company_error = _normalize_company_field(fields)
    if company_error:
        return {"success": False, "message": company_error}

    bad = _validate_fields(fields)
    if bad:
        return {"success": False, "message": bad}

    try:
        r = await run_in_threadpool(_register_core, **fields, source_call_id=cleaned.get("source_call_id"))
    except Exception as e:
        print(f"[register][error] {e}")
        return {"success": False, "message": SPEECH_ERROR}
    return {
        "success": r["success"],
        "message": _speech_for(r),
        "request_id": r["request_id"],
        "entry_time": r["entry_time"],
        "elapsed_ms": r["elapsed_ms"],
        "push_elapsed_ms": r["push_elapsed_ms"],
        "push_detail": r["push_detail"],
    }


@app.post("/vapi/register_visitor")
async def vapi_register_visitor(request: Request):
    """适配 Vapi 的 tool-calls 信封。无论成功失败都返回 HTTP 200 + results 数组，
    result/error 必须是单行字符串。"""
    body = await request.json()
    message = body.get("message", {}) or {}
    tool_calls = message.get("toolCallList") or []
    call_id = (message.get("call") or {}).get("id")

    results = []
    for tc in tool_calls:
        tool_call_id = tc.get("id")
        args = tc.get("arguments") or {}
        if isinstance(args, str):  # 有些情况下 arguments 是 JSON 字符串
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}

        fields = {
            "plate_number": (args.get("plate_number") or "").strip(),
            "company": (args.get("company") or "").strip(),
            "phone": (args.get("phone") or "").strip(),
            "reason": (args.get("reason") or "").strip(),
        }
        missing = [k for k, v in fields.items() if not v]
        if missing:
            results.append({"toolCallId": tool_call_id, "error": _missing_message(missing)})
            continue

        company_error = _normalize_company_field(fields)
        if company_error:
            results.append({"toolCallId": tool_call_id, "result": company_error})
            continue

        bad = _validate_fields(fields)
        if bad:
            results.append({"toolCallId": tool_call_id, "result": bad})
            continue

        try:
            r = await run_in_threadpool(_register_core, **fields, source_call_id=call_id)
            results.append({"toolCallId": tool_call_id, "result": _speech_for(r)})
        except Exception as e:
            print(f"[vapi][error] {e}")
            results.append({"toolCallId": tool_call_id, "result": SPEECH_ERROR})

    return {"results": results}


@app.post("/lookup_visitor")
async def lookup_visitor(request: Request):
    """对话内回访识别入口（扁平 JSON，Vapi API Request 用）。
    Agent 拿到车牌后调用；命中则念返回的 message 确认，确认后用返回的 company/reason/phone 复用登记。"""
    try:
        raw = await request.json()
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    plate, phone = "", ""
    for k, v in raw.items():
        key = k.strip() if isinstance(k, str) else k
        val = v.strip() if isinstance(v, str) else v
        if key == "plate_number":
            plate = val or ""
        elif key == "phone":
            phone = val or ""
    try:
        return await run_in_threadpool(_lookup_core, plate, phone)
    except Exception as e:
        print(f"[lookup][error] {e}")
        return {"found": False, "visit_count": 0, "message": ""}


@app.post("/vapi/lookup_visitor")
async def vapi_lookup_visitor(request: Request):
    """适配 Vapi 信封的 lookup（备用，方案 B Function）。
    result 为紧凑 JSON 字符串，Agent 读取后据此说确认句、复用历史字段。"""
    body = await request.json()
    message = body.get("message", {}) or {}
    tool_calls = message.get("toolCallList") or []
    results = []
    for tc in tool_calls:
        tool_call_id = tc.get("id")
        args = tc.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        plate = (args.get("plate_number") or "").strip()
        phone = (args.get("phone") or "").strip()
        try:
            r = await run_in_threadpool(_lookup_core, plate, phone)
            results.append({"toolCallId": tool_call_id, "result": json.dumps(r, ensure_ascii=False)})
        except Exception as e:
            print(f"[vapi][lookup][error] {e}")
            results.append({"toolCallId": tool_call_id, "result": json.dumps({"found": False}, ensure_ascii=False)})
    return {"results": results}


@app.get("/visitors")
def list_visitors():
    return db.list_visitors()


@app.get("/visit/by-call/{call_id}")
def visit_by_call(call_id: str):
    """设备身份用（决策 012）：Web 通话结束后，访客手机用本次 call.id 取回本次登记的手机号，
    存进本机 localStorage 当作「来电号码」；下次扫码即在接通时按手机号识别回访（模拟 caller ID）。

    只读。依赖 Vapi register 工具体里带上 source_call_id={{call.id}}；没带时查不到、字段返回 null，
    前端静默跳过（功能优雅失效，不报错）。车牌一并回传仅作兼容/调试。"""
    row = db.find_by_call_id(call_id)
    if not row:
        return {"phone": None, "plate_number": None}
    return {"phone": row.get("phone"), "plate_number": row.get("plate_number")}


@app.get("/guard", response_class=HTMLResponse)
def guard_console():
    """轻量门卫查询后台：Server酱负责单向推送，主动查询走这个页面。"""
    return HTMLResponse(GUARD_CONSOLE_HTML)


@app.get("/call", response_class=HTMLResponse)
def mobile_call():
    """手机扫码后的访客入口：用 Vapi Web Call 连接同一个门卫 Assistant。"""
    return HTMLResponse(_render_call_html())


@app.get("/qr", response_class=HTMLResponse)
def call_qr(request: Request):
    """展示当前 /call 地址二维码。cloudflared 地址每次变，二维码也随请求 Host 生成。"""
    call_url = _public_url(request, "/call")
    return HTMLResponse(_render_qr_html(call_url))


@app.post("/guard/query")
async def guard_query(request: Request):
    """门卫查询 Agent：自然语言问访客数据。无 LLM key 时自动降级关键词规则。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    question = (body.get("question") or "").strip() if isinstance(body, dict) else ""
    if not question:
        return {"reply": "请说要查什么，比如：今天来了几辆车。"}
    try:
        return query_agent.answer(question)
    except Exception as e:
        print(f"[guard_query][error] {e}")
        return {"reply": "查询出错了，请稍后再试。"}


def _public_url(request: Request, path: str) -> str:
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip()
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}{path}"


def _render_call_html() -> str:
    """手机访客入口：用 Vapi Web SDK 自控通话按钮（替代黑盒 embed widget）。

    自建 UI 解决三件事：① 响应式居中、适配手机屏；② 连接/失败/重试显式状态，
    不再静默退回；③ 检测微信内置浏览器（WebRTC/麦克风用不了）时给醒目横幅、引导用系统浏览器。
    """
    configured = bool(VAPI_PUBLIC_KEY and VAPI_ASSISTANT_ID)

    if configured:
        call_section = """
      <div id="wx-top-arrow" class="wx-top-arrow" style="display:none">↑ 右上角 ⋯ → 在浏览器打开</div>
      <div id="wechat-guide" class="wxguide" style="display:none">
        <h2 class="wxguide-title">换浏览器打开，即可语音登记</h2>
        <ol class="wxguide-steps">
          <li><b>①</b> 点屏幕<b>右上角 ⋯</b></li>
          <li><b>②</b> 选 <b>「在浏览器打开」</b></li>
        </ol>
        <p class="wxguide-note">微信里用不了麦克风，换系统浏览器 1 秒搞定；打开后点「开始通话」即可。</p>
      </div>
      <div class="callbox" id="callbox">
        <button id="call-btn" class="call-btn" disabled>加载中…</button>
        <p id="status" class="status">正在加载通话组件…</p>
      </div>
"""
        script_block = """
  <script type="module">
    const PUBLIC_KEY = __PUBLIC_KEY__;
    const ASSISTANT_ID = __ASSISTANT_ID__;
    const PHONE_KEY = "vg_known_phone";
    const btn = document.getElementById("call-btn");
    const statusEl = document.getElementById("status");
    const isWeChat = /MicroMessenger/i.test(navigator.userAgent);

    // 设备身份（决策 012）：把本机上次登记的手机号当作「来电号码」。同一手机再扫码＝同一来电号码，
    // 接通时按它查最近一次历史 → 复述车牌/公司/事由、且全程不再追问手机号（模拟电话 caller ID）。
    let knownPhone = "";
    try {
      knownPhone = localStorage.getItem(PHONE_KEY) || "";
      localStorage.removeItem("vg_known_plate");   // 清掉旧版按车牌存的键
    } catch (e) {}

    let vapi = null;
    let state = "idle";          // idle | connecting | active
    let connectTimer = null;
    let callId = null;
    // 回访历史：加载时按本机手机号静默查最近一次，命中则开场白复述车牌/公司/事由。
    let knownInfo = null;        // null=未查/查不到；{found,plate_number,company,reason,phone}=命中
    let knownInfoPromise = null;

    function idleHint() {
      if (knownInfo && knownInfo.found) {
        return "本机来过：上次去" + (knownInfo.company || "") + "，接通后确认即可";
      }
      if (knownPhone) return "本机登记过，接通后无需重报手机号";
      return "点击开始，并允许麦克风权限";
    }

    function setIdle(msg) {
      state = "idle";
      btn.textContent = "开始通话";
      btn.disabled = false;
      btn.classList.remove("active");
      statusEl.textContent = msg || idleHint();
    }
    function setConnecting() {
      state = "connecting";
      btn.textContent = "连接中…";
      btn.disabled = true;
      btn.classList.remove("active");
      statusEl.textContent = "正在连接，请稍候…";
      clearTimeout(connectTimer);
      connectTimer = setTimeout(function () {
        if (state === "connecting") {
          try { if (vapi) vapi.stop(); } catch (e) {}
          setIdle("连接超时，请重试（信号弱可换 WiFi 或手机流量）");
        }
      }, 20000);
    }
    function setActive() {
      state = "active";
      clearTimeout(connectTimer);
      btn.textContent = "结束通话";
      btn.disabled = false;
      btn.classList.add("active");
      statusEl.textContent = "已接通，请直接说话…";
    }

    // 回访预取：用本机手机号静默查最近一次历史，供开场白复述车牌/公司/事由 + 命中提示。失败静默降级。
    async function prefetchKnown() {
      if (!knownPhone) return;
      try {
        const r = await fetch("/lookup_visitor", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ phone: knownPhone }),
        });
        knownInfo = r.ok ? (await r.json()) : { found: false };
      } catch (e) {
        knownInfo = { found: false };
      }
      if (state === "idle") statusEl.textContent = idleHint();
    }

    // 通话结束后，用 call.id 回查本次登记的手机号，记到本机当「来电号码」，供下次扫码识别回访。
    async function rememberPhone() {
      if (!callId) return;
      try {
        const r = await fetch("/visit/by-call/" + encodeURIComponent(callId));
        if (!r.ok) return;
        const data = await r.json();
        if (data && data.phone) {
          localStorage.setItem(PHONE_KEY, data.phone);
        }
      } catch (e) { console.warn("[remember]", e); }
    }

    if (isWeChat) {
      // 微信内置浏览器拿不到麦克风，也无法自动跳出 → 显式两步引导用户切到系统浏览器
      document.getElementById("wechat-guide").style.display = "block";
      document.getElementById("wx-top-arrow").style.display = "block";
      document.getElementById("callbox").style.display = "none";
    } else {
      knownInfoPromise = prefetchKnown();   // 与 SDK 加载并行，点按钮前一般已就绪
      let Vapi;
      try {
        ({ default: Vapi } = await import("https://esm.sh/@vapi-ai/web"));
      } catch (e) {
        console.error("[vapi:import]", e);
        btn.textContent = "加载失败";
        statusEl.textContent = "通话组件加载失败，请刷新或换网络重试";
        throw e;
      }
      vapi = new Vapi(PUBLIC_KEY);
      vapi.on("call-start", setActive);
      vapi.on("call-end", async function () {
        await rememberPhone();
        setIdle("通话已结束，可再次开始");
      });
      vapi.on("error", function (e) {
        console.error("[vapi:error]", e);
        const m = (e && (e.errorMsg || (e.error && e.error.message) || e.message)) || "连接失败，请重试";
        clearTimeout(connectTimer);
        setIdle("出错了：" + m);
      });
      btn.addEventListener("click", async function () {
        if (state === "active") { vapi.stop(); return; }
        if (state === "connecting") return;
        callId = null;
        setConnecting();
        // 回访开场白：本机有「来电号码」(手机号) → 视作同一来电，全程不再问手机号；
        //   查到最近历史 → 复述车牌+公司+事由让司机确认；查不到(如清库后) → 只问车牌+公司+事由；
        //   新设备(无号) → 保持默认开场，照常采集含手机号。
        const overrides = {
          variableValues: {
            known_phone: knownPhone,
            known_plate: "",
            known_company: "",
            known_reason: "",
          },
        };
        if (knownPhone) {
          if (knownInfo === null && knownInfoPromise) { try { await knownInfoPromise; } catch (e) {} }
          if (knownInfo && knownInfo.found) {
            overrides.variableValues.known_plate = knownInfo.plate_number || "";
            overrides.variableValues.known_company = knownInfo.company || "";
            overrides.variableValues.known_reason = knownInfo.reason || "";
            overrides.firstMessage =
              "您好，检测到您之前来过，这次还是开" + (knownInfo.plate_number || "") +
              "，去" + (knownInfo.company || "") + "、" + (knownInfo.reason || "") +
              "吗？若入园信息有更新也请告诉我。";
          } else {
            overrides.firstMessage =
              "您好，欢迎再次光临，今天开什么车、找哪家公司、办什么事儿？";
          }
        }
        try {
          const call = await vapi.start(ASSISTANT_ID, overrides);
          if (call && call.id) callId = call.id;
        } catch (e) {
          console.error("[vapi:start]", e);
          clearTimeout(connectTimer);
          setIdle("无法开始：请允许麦克风权限后重试");
        }
      });
      setIdle();
    }
  </script>
"""
        script_block = script_block.replace(
            "__PUBLIC_KEY__", json.dumps(VAPI_PUBLIC_KEY)
        ).replace("__ASSISTANT_ID__", json.dumps(VAPI_ASSISTANT_ID))
    else:
        call_section = """
      <div class="warning">
        还没配置 Vapi Web Call。请在 <code>backend/.env</code> 填入
        <code>VAPI_PUBLIC_KEY</code> 和 <code>VAPI_ASSISTANT_ID</code> 后重启后端。
      </div>
"""
        script_block = ""

    template = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <title>AI 门卫访客登记</title>
  <style>
    :root { color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; background: linear-gradient(160deg, #ecfeff 0%, #f8fafc 48%, #f0fdf4 100%); color: #0f172a; }
    main { max-width: 520px; margin: 0 auto; padding: 28px 20px 40px; }
    .hero { background: rgba(255,255,255,.92); border: 1px solid #dbeafe; border-radius: 28px; padding: 26px 22px; box-shadow: 0 22px 60px rgba(15, 23, 42, .12); }
    .badge { display: inline-flex; align-items: center; border-radius: 999px; background: #ccfbf1; color: #0f766e; padding: 6px 11px; font-weight: 700; font-size: 13px; }
    h1 { margin: 18px 0 10px; font-size: 32px; line-height: 1.12; letter-spacing: -.04em; }
    p { margin: 0; color: #475569; line-height: 1.65; font-size: 16px; }
    .steps { margin: 22px 0; padding: 0; list-style: none; display: grid; gap: 10px; }
    .steps li { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 16px; padding: 12px 14px; color: #334155; }
    .callbox { margin-top: 22px; display: grid; place-items: center; gap: 10px; }
    .call-btn { appearance: none; border: none; cursor: pointer; width: min(320px, 100%); padding: 18px 24px; border-radius: 999px; background: #0f766e; color: #fff; font-size: 19px; font-weight: 700; box-shadow: 0 10px 24px rgba(15,118,110,.35); transition: transform .05s ease, background .2s ease; }
    .call-btn:active { transform: scale(.98); }
    .call-btn:disabled { background: #94a3b8; box-shadow: none; cursor: not-allowed; }
    .call-btn.active { background: #dc2626; box-shadow: 0 10px 24px rgba(220,38,38,.35); }
    .status { margin: 0; font-size: 14px; color: #64748b; min-height: 20px; text-align: center; }
    .hint { margin-top: 18px; font-size: 13px; color: #64748b; }
    .warning { border: 1px solid #fbbf24; background: #fffbeb; color: #92400e; border-radius: 18px; padding: 16px; line-height: 1.6; margin-bottom: 6px; }
    .wx-top-arrow { position: fixed; top: 6px; right: 10px; z-index: 50; background: #0f766e; color: #fff; padding: 8px 12px; border-radius: 12px; font-size: 13px; font-weight: 700; box-shadow: 0 8px 22px rgba(15,118,110,.45); animation: bob 1s ease-in-out infinite; }
    @keyframes bob { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-5px); } }
    .wxguide { margin-top: 22px; border: 1px solid #99f6e4; background: #f0fdfa; color: #134e4a; border-radius: 18px; padding: 20px; }
    .wxguide-title { margin: 0 0 14px; font-size: 20px; }
    .wxguide-steps { margin: 0; padding: 0; list-style: none; display: grid; gap: 10px; }
    .wxguide-steps li { background: #fff; border: 1px solid #ccfbf1; border-radius: 12px; padding: 12px 14px; font-size: 17px; }
    .wxguide-steps b { color: #0f766e; }
    .wxguide-note { margin: 14px 0 0; font-size: 13px; color: #475569; line-height: 1.6; }
    code { background: rgba(15, 23, 42, .08); border-radius: 6px; padding: 1px 5px; }
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <span class="badge">工业园区入口</span>
      <h1>AI 门卫访客登记</h1>
      <p>请点击下方按钮，用手机麦克风告诉 AI 门卫：车牌号、来访公司、来访事由和手机号。登记完成后，保安会收到微信通知。</p>
      <ul class="steps">
        <li>1. 点击「开始通话」并允许麦克风权限</li>
        <li>2. 按语音提示说出访客信息</li>
        <li>3. 听到「已通知保安」后，请稍等放行</li>
      </ul>
__CALL_SECTION__
      <p class="hint">建议用系统浏览器（Safari / Chrome）打开；微信内置浏览器无法使用麦克风。</p>
    </section>
  </main>
__SCRIPT_BLOCK__
</body>
</html>
"""
    return template.replace("__CALL_SECTION__", call_section).replace(
        "__SCRIPT_BLOCK__", script_block
    )


def _render_qr_html(call_url: str) -> str:
    safe_call_url = escape(call_url)
    qr_src = "https://api.qrserver.com/v1/create-qr-code/?size=280x280&data=" + quote(call_url, safe="")
    return f"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AI 门卫扫码入口</title>
  <style>
    :root {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; background: #f8fafc; color: #0f172a; }}
    .card {{ width: min(520px, calc(100vw - 40px)); background: white; border: 1px solid #e2e8f0; border-radius: 28px; padding: 30px; text-align: center; box-shadow: 0 20px 55px rgba(15, 23, 42, .12); }}
    h1 {{ margin: 0 0 10px; font-size: 30px; }}
    p {{ color: #475569; line-height: 1.6; }}
    img {{ width: 280px; height: 280px; margin: 20px auto; display: block; border-radius: 18px; border: 1px solid #e2e8f0; }}
    a {{ color: #0f766e; overflow-wrap: anywhere; }}
    .note {{ margin-top: 18px; font-size: 14px; color: #64748b; }}
  </style>
</head>
<body>
  <main class="card">
    <h1>扫码呼叫 AI 门卫</h1>
    <p>用手机扫码打开访客登记页面，点击「开始通话」后直接和 AI 门卫对话。</p>
    <img src="{qr_src}" alt="手机呼叫入口二维码" />
    <p><a href="{safe_call_url}">{safe_call_url}</a></p>
    <p class="note">建议用<b>手机相机</b>扫码，可直接在浏览器打开；若用微信扫码，请在右上角「⋯」选「在浏览器打开」再开始通话。</p>
  </main>
</body>
</html>
"""


GUARD_CONSOLE_HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>门卫查询后台</title>
  <style>
    :root { color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    body { margin: 0; background: #f6f7fb; color: #1f2937; }
    main { max-width: 880px; margin: 48px auto; padding: 0 20px; }
    .card { background: white; border: 1px solid #e5e7eb; border-radius: 18px; padding: 24px; box-shadow: 0 10px 30px rgba(15, 23, 42, .06); }
    h1 { margin: 0 0 8px; font-size: 28px; }
    p { margin: 0 0 18px; color: #6b7280; }
    textarea { width: 100%; box-sizing: border-box; min-height: 92px; border: 1px solid #d1d5db; border-radius: 12px; padding: 14px; font-size: 16px; resize: vertical; }
    button { margin-top: 12px; border: 0; border-radius: 999px; background: #0f766e; color: white; padding: 11px 20px; font-size: 15px; cursor: pointer; }
    button:disabled { opacity: .55; cursor: wait; }
    .examples { display: flex; flex-wrap: wrap; gap: 8px; margin: 16px 0; }
    .chip { border: 1px solid #d1d5db; background: #f9fafb; color: #374151; border-radius: 999px; padding: 7px 11px; font-size: 14px; cursor: pointer; }
    .answer { white-space: pre-wrap; margin-top: 18px; background: #ecfdf5; border: 1px solid #99f6e4; border-radius: 14px; padding: 16px; min-height: 50px; }
    details { margin-top: 14px; color: #6b7280; }
    pre { overflow: auto; background: #111827; color: #e5e7eb; border-radius: 12px; padding: 14px; }
  </style>
</head>
<body>
  <main>
    <section class="card">
      <h1>门卫查询后台</h1>
      <p>输入自然语言问题，系统会用 LLM 抽取结构化意图，再走参数化 SQL 查询访客库。</p>
      <textarea id="question" placeholder="比如：今天来了几辆车？最近7天哪家公司来访最多？昨天送货的有哪些？"></textarea>
      <div class="examples">
        <span class="chip">今天来了几辆车？</span>
        <span class="chip">最近7天有哪些访客？</span>
        <span class="chip">本周哪家公司来访最多？</span>
        <span class="chip">本月事由分布是什么？</span>
        <span class="chip">手机号13800138000来过几次？</span>
      </div>
      <button id="ask">查询</button>
      <div id="answer" class="answer">等待查询。</div>
      <details>
        <summary>调试信息</summary>
        <pre id="debug">{}</pre>
      </details>
    </section>
  </main>
  <script>
    const q = document.querySelector("#question");
    const answer = document.querySelector("#answer");
    const debug = document.querySelector("#debug");
    const btn = document.querySelector("#ask");
    document.querySelectorAll(".chip").forEach(chip => {
      chip.addEventListener("click", () => { q.value = chip.textContent; q.focus(); });
    });
    async function ask() {
      const question = q.value.trim();
      if (!question) { answer.textContent = "先输入要查什么。"; return; }
      btn.disabled = true;
      answer.textContent = "查询中...";
      debug.textContent = "{}";
      try {
        const res = await fetch("/guard/query", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question })
        });
        const data = await res.json();
        answer.textContent = data.reply || "没有返回结果。";
        debug.textContent = JSON.stringify(data, null, 2);
      } catch (err) {
        answer.textContent = "查询失败，请确认后端服务还在运行。";
        debug.textContent = String(err);
      } finally {
        btn.disabled = false;
      }
    }
    btn.addEventListener("click", ask);
    q.addEventListener("keydown", event => {
      if ((event.ctrlKey || event.metaKey) && event.key === "Enter") ask();
    });
  </script>
</body>
</html>
"""


# 返回给语音模型的话术，直接用中文，确保 TTS 念得对、措辞统一。
# 用词避坑：用"保安"不用"门卫"（Azure 中文 TTS 易把"门卫"念成"满位"）。
SPEECH_SUCCESS = "好的，信息登记好了，我这就通知保安放行，您稍等。"
SPEECH_SUCCESS_REVISIT = "您之前来过，欢迎回来！信息登记好了，我这就通知保安放行，您稍等。"
SPEECH_FAIL = "信息登记上了，不过通知保安没成功，麻烦您稍等，我叫人工处理。"
SPEECH_IDEMPOTENT = "这辆车刚登记过了，您稍等放行就行。"
SPEECH_ERROR = "不好意思，系统这会儿有点问题，麻烦您稍等，我叫人工来处理。"
SPEECH_BAD_PHONE = "手机号好像不太对，麻烦您再说一遍完整的 11 位手机号。"
SPEECH_BAD_PLATE = "车牌号好像没太清楚，麻烦您把完整车牌号再说一遍。"

# 字段格式校验（决策 001 / 011）：后端是权威防线。
# 手机号：归一化去分隔符后须为 11 位、1 开头。
# 车牌：归一化与省份校验下沉到 plate_registry（省份闭集 + 近音纠正 + 格式）。
_PHONE_RE = re.compile(r"^1\d{10}$")


def _normalize_plate(s: str) -> str:
    """尽力归一（含省份近音纠正），不抛错；供回访查询等场景复用。"""
    return plate_registry.clean_plate(s)


def _normalize_phone(s: str) -> str:
    # 先把口语数字（幺→1、两→2…）归一，再去分隔符；应对 STT/LLM 把 1 写成「幺」
    s = plate_registry.normalize_cn_digits(s or "")
    return re.sub(r"[\s\-()（）]", "", s)


def _validate_fields(fields) -> Optional[str]:
    """就地归一化 phone/plate 并校验格式。通过返回 None，否则返回中文重说话术。"""
    fields["phone"] = _normalize_phone(fields["phone"])
    try:
        fields["plate_number"] = plate_registry.normalize_plate(fields["plate_number"])
    except plate_registry.InvalidPlateError:
        return SPEECH_BAD_PLATE
    if not _PHONE_RE.match(fields["phone"]):
        return SPEECH_BAD_PHONE
    return None


def _normalize_company_field(fields) -> Optional[str]:
    try:
        fields["company"] = normalize_company(fields["company"])
        return None
    except UnknownCompanyError as e:
        if e.suggestions:
            guess = "、".join(e.suggestions)
            return f"园区里没直接查到这个来访单位。您说的是{guess}吗？如果不是，请再说一遍公司全称。"
        return f"园区里没查到这个来访单位。请确认公司名称，目前可登记的公司有：{company_help_text()}。"


FIELD_CN = {
    "plate_number": "车牌号",
    "company": "来访单位",
    "phone": "手机号",
    "reason": "来访事由",
}


def _speech_for(r) -> str:
    if r["idempotent"]:
        return SPEECH_IDEMPOTENT
    if not r["success"]:
        return SPEECH_FAIL
    return SPEECH_SUCCESS_REVISIT if r.get("is_revisit") else SPEECH_SUCCESS


def _missing_message(missing) -> str:
    cn = "、".join(FIELD_CN.get(k, k) for k in missing)
    return f"还缺这些信息：{cn}"


def _format_message(plate_number, company, phone, reason, entry_time, revisit_count=0, last_visit=None) -> str:
    revisit_block = ""
    if revisit_count and last_visit:
        last_date = (last_visit.get("entry_time") or "")[:10]
        revisit_block = (
            f"【回访】历史到访 {revisit_count} 次，"
            f"上次 {last_date} 去{last_visit.get('company', '')}（{last_visit.get('reason', '')}）\n\n"
        )
    return (
        "访客车辆登记\n\n"
        f"车牌号：{plate_number}\n"
        f"来访单位：{company}\n"
        f"手机号：{phone}\n"
        f"来访事由：{reason}\n"
        f"入场时间：{entry_time}\n\n"
        f"{revisit_block}"
        "状态：待保安确认放行"
    )
