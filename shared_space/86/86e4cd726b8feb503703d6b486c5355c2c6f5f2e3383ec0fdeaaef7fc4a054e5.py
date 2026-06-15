import asyncio
import websockets
import json
import os
import subprocess

async def listen():
    # استبدل الآي بي بآي بي الرازباري باي (Tailscale)
    uri = "ws://100.93.140.49:8123/ws/linux_machine" 
    
    while True:
        try:
            async with websockets.connect(uri) as websocket:
                print("🟢 Linux Agent Online & Connected")
                # إرسال تأكيد اتصال للسيرفر
                await websocket.send(json.dumps({"type": "status", "data": "connected"}))
                
                while True:
                    message = await websocket.recv()
                    data = json.loads(message)
                    action = data.get("action")
                    print(f"📩 Action Received: {action}")

                    if action == "shutdown":
                        # إيقاف التشغيل في لينكس (يتطلب صلاحيات أو ضبط sudo)
                        os.system("poweroff")
                    
                    elif action == "show_msg":
                        # إرسال إشعار لسطح المكتب في لينكس (نظام GNOME/KDE)
                        msg_text = data.get("text", "PINGO: Hello!")
                        os.system(f'notify-send "PINGO Control" "{msg_text}"')
                    
                    elif action == "youtube_play":
                        url = data.get("url")
                        # فتح الرابط في المتصفح الافتراضي للينكس
                        subprocess.Popen(["xdg-open", url])

                    elif action == "terminal_cmd":
                        # ميزة إضافية: تنفيذ أمر تيرمينال
                        cmd = data.get("cmd")
                        os.system(cmd)

        except Exception as e:
            print(f"🔴 Connection lost: {e}. Retrying in 5 seconds...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(listen())
