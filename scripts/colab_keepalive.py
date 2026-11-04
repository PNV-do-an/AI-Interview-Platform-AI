#!/usr/bin/env python3
"""
Colab Session Keepalive Script
Tự động ping mỗi 9 phút để tránh bị timeout (session max 12h)
Chạy trong một cell riêng, để chạy background liên tục
"""

import time
import threading
from datetime import datetime
from IPython.display import display, HTML

# Configuration
PING_INTERVAL_MINUTES = 9  # Ping trước timeout 1 phút

def send_ping():
    """Send heartbeat ping to keep session alive"""
    try:
        from google.colab import output
        
        output.eval_js("""
            // Simulate user activity
            const event = new MouseEvent('mousedown', {
                bubbles: true,
                cancelable: true,
                view: window
            });
            document.body.dispatchEvent(event);
        """)
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Ping sent - Session maintained")
        
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Ping failed: {e}")

def keepalive_loop():
    """Main keepalive loop"""
    print("=" * 60)
    print("🔄 COLAB SESSION KEEPSERVER STARTED")
    print(f"⏱️ Interval: Every {PING_INTERVAL_MINUTES} minutes")
    print("💡 To stop: Run another cell or disconnect")
    print("=" * 60)
    
    start_time = datetime.now()
    timer = 0
    
    while True:
        send_ping()
        timer += 1
        
        # Calculate elapsed time
        elapsed = datetime.now() - start_time
        hours = int(elapsed.total_seconds() // 3600)
        minutes = int((elapsed.total_seconds() % 3600) // 60)
        
        if timer % 7 == 0:  # Print status every ~1 hour
            print(f"\n📊 Status: Running for {hours}h {minutes}m\n")
        
        time.sleep(PING_INTERVAL_MINUTES * 60)

# Start the keepalive thread
keepalive_thread = threading.Thread(target=keepalive_loop, daemon=True)
keepalive_thread.start()

print("✅ Keepalive server is running in background!")
print("You can close this cell and the ping will continue.")
