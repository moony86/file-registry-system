#!/usr/bin/env python3
"""
PINGO Agent - Linux only
يتصل بخادم PINGO عبر WebSocket وينفذ الأوامر بدعم كامل للينكس
"""

import asyncio
import json
import logging
import os
import sys
import platform
import subprocess
import shlex
import webbrowser

import websockets
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

# =========================
# إعدادات التسجيل
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("pingo-agent-linux")

# =========================
# الإعدادات
# =========================
SERVER_URL = os.getenv("PINGO_SERVER", "ws://100.93.140.49:8123/ws/linux_machine")
HEARTBEAT_INTERVAL = 30
BACKOFF_MIN = 2
BACKOFF_MAX = 60

SYSTEM = platform.system()
if SYSTEM != "Linux":
    log.warning("⚠️ هذا الوكيل مصمم للينكس فقط. قد لا تعمل الأوامر بشكل صحيح على %s", SYSTEM)

# =========================
# دوال مساعدة
# =========================
async def run_cmd(cmd: str, shell=True) -> tuple:
    """تنفيذ أمر وإرجاع (returncode, stdout, stderr) بشكل غير متزامن."""
    loop = asyncio.get_event_loop()
    def _run():
        try:
            proc = subprocess.run(
                cmd if shell else shlex.split(cmd),
                capture_output=True,
                text=True,
                shell=shell
            )
            return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
        except Exception as e:
            return -1, "", str(e)
    return await loop.run_in_executor(None, _run)

# =========================
# معالجات الأوامر (لينكس)
# =========================
async def handle_shutdown(data: dict, ws) -> str:
    delay = data.get("delay", 1)  # دقائق
    if delay == 0:
        cmd = "shutdown -h now"
    else:
        cmd = f"shutdown -h +{delay}"
    log.info(f"🛑 إيقاف التشغيل: {cmd}")
    rc, out, err = await run_cmd(cmd)
    if rc != 0:
        # إذا فشل الأمر باستخدام shutdown (ربما لا صلاحيات) نعطي خطأ واضح
        return f"shutdown_failed: {err or 'تحتاج صلاحيات الجذر أو sudo'}"
    return "shutdown_scheduled"

async def handle_restart(data: dict, ws) -> str:
    delay = data.get("delay", 1)
    if delay == 0:
        cmd = "shutdown -r now"
    else:
        cmd = f"shutdown -r +{delay}"
    rc, out, err = await run_cmd(cmd)
    if rc != 0:
        return f"restart_failed: {err}"
    return "restart_scheduled"

async def handle_show_msg(data: dict, ws) -> str:
    """إظهار رسالة باستخدام notify-send (يفضل) أو zenity."""
    msg = data.get("text", "Hello from PINGO")
    title = data.get("title", "PINGO")
    # محاولة notify-send
    rc, out, err = await run_cmd(f'notify-send "{title}" "{msg}"')
    if rc == 0:
        return "message_shown (notify-send)"
    # محاولة zenity
    rc2, out2, err2 = await run_cmd(f'zenity --info --title="{title}" --text="{msg}"')
    if rc2 == 0:
        return "message_shown (zenity)"
    # بديل: الطباعة في السجل
    log.warning("لا يوجد notify-send أو zenity. تم تسجيل الرسالة في السجل.")
    log.info(f"رسالة: [{title}] {msg}")
    return "message_logged"

async def handle_open_url(data: dict, ws) -> str:
    """فتح رابط في المتصفح الافتراضي."""
    url = data.get("url")
    if not url:
        raise ValueError("الرابط مطلوب")
    # استخدام webbrowser.open (يعمل على لينكس باستخدام xdg-open)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: webbrowser.open(url))
    log.info(f"🌐 فتح الرابط: {url}")
    return "url_opened"

async def handle_ping(data: dict, ws) -> str:
    """الرد على أمر ping."""
    return "pong_sent"

async def handle_run_cmd(data: dict, ws) -> str:
    """تنفيذ أمر عشوائي (بحذر)."""
    cmd = data.get("cmd")
    if not cmd:
        raise ValueError("الأمر مطلوب")
    rc, out, err = await run_cmd(cmd)
    return f"exit_code:{rc}, stdout:{out[:200]}, stderr:{err[:200]}"

async def handle_volume(data: dict, ws) -> str:
    """تغيير مستوى الصوت عبر pactl (PulseAudio) أو amixer."""
    level = data.get("level", 50)
    # pactl
    rc, out, err = await run_cmd(f"pactl set-sink-volume @DEFAULT_SINK@ {level}%")
    if rc == 0:
        return f"volume_set:{level}% (pactl)"
    # amixer
    rc2, out2, err2 = await run_cmd(f"amixer set Master {level}%")
    if rc2 == 0:
        return f"volume_set:{level}% (amixer)"
    return f"volume_failed: {err or err2}"

# سجل الأوامر المدعومة
HANDLERS = {
    "shutdown":     handle_shutdown,
    "restart":      handle_restart,
    "show_msg":     handle_show_msg,
    "open_url":     handle_open_url,
    "youtube_play": handle_open_url,   # نفس معالج الفتح
    "ping":         handle_ping,
    "run_cmd":      handle_run_cmd,
    "volume":       handle_volume,
}

# =========================
# نبضات القلب ومعالجة الرسائل
# =========================
async def heartbeat_loop(ws):
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        try:
            await ws.send(json.dumps({"type": "ping", "ts": __import__("time").time()}))
            log.debug("💓 نبضات القلب")
        except Exception:
            break

async def handle_command(msg: dict, ws):
    action = msg.get("action", "unknown")
    cmd_id = msg.get("command_id", "no-id")
    data = msg.get("data", {})

    log.info(f"▶️ الأمر: {action} [{cmd_id[:8]}…]")

    try:
        handler = HANDLERS.get(action)
        if not handler:
            raise NotImplementedError(f"أمر غير معروف: '{action}'")

        # إرسال pong فوري للـ ping
        if action == "ping":
            await ws.send(json.dumps({"type": "pong", "command_id": cmd_id}))

        result = await handler(data, ws)

        await ws.send(json.dumps({
            "type": "ack",
            "command_id": cmd_id,
            "status": "done",
            "result": result,
        }))
        log.info(f"✅ تم تأكيد الأمر: {cmd_id[:8]}… → {result}")

    except NotImplementedError as e:
        log.warning(str(e))
        await ws.send(json.dumps({
            "type": "ack",
            "command_id": cmd_id,
            "status": "unsupported",
            "error": str(e),
        }))
    except Exception as e:
        log.error(f"فشل معالجة الأمر [{action}]: {e}")
        await ws.send(json.dumps({
            "type": "ack",
            "command_id": cmd_id,
            "status": "failed",
            "error": str(e),
        }))

async def receiver_loop(ws):
    async for raw in ws:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            log.warning(f"رسالة غير صالحة: {raw}")
            continue

        msg_type = msg.get("type")
        if msg_type == "command":
            asyncio.create_task(handle_command(msg, ws))
        elif msg_type == "ping":
            await ws.send(json.dumps({"type": "pong"}))
        else:
            log.debug(f"استقبلت: {msg}")

# =========================
# الاتصال وإعادة المحاولة
# =========================
async def connect():
    backoff = BACKOFF_MIN
    while True:
        try:
            log.info(f"📡 الاتصال بـ {SERVER_URL}")
            async with websockets.connect(
                SERVER_URL,
                ping_interval=None,
                ping_timeout=None,
                close_timeout=5,
            ) as ws:
                log.info("🟢 متصل")
                backoff = BACKOFF_MIN

                # إرسال معلومات الجهاز
                await ws.send(json.dumps({
                    "type": "status",
                    "data": "connected",
                    "hostname": platform.node(),
                    "os": SYSTEM,
                }))

                hb_task = asyncio.create_task(heartbeat_loop(ws))
                try:
                    await receiver_loop(ws)
                finally:
                    hb_task.cancel()

        except (ConnectionClosedOK, ConnectionClosedError) as e:
            log.warning(f"🔴 قطع الاتصال: {e}")
        except OSError as e:
            log.warning(f"🔴 خطأ في الشبكة: {e}")
        except Exception as e:
            log.error(f"🔴 خطأ غير متوقع: {e}")

        log.info(f"⏳ إعادة المحاولة بعد {backoff} ثانية…")
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, BACKOFF_MAX)

# =========================
# التشغيل
# =========================
def main():
    log.info(f"🚀 تشغيل وكيل PINGO لنظام لينكس على {platform.node()}")
    # التأكد من وجود webbrowser (موجود دوماً)
    try:
        asyncio.run(connect())
    except KeyboardInterrupt:
        log.info("تم الإيقاف بواسطة المستخدم")
        sys.exit(0)

if __name__ == "__main__":
    main()
