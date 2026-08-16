"""TSF 模块冒烟验证：Activate / 焦点事件 / 轮询 / 停止 不崩溃。

真实输入法组字行为需实机验证（沙箱无输入法交互）。
"""
import sys
import time

sys.path.insert(0, r'D:\dz\typing-tracker')
sys.path.insert(0, r'D:\dz\typing-tracker\.deps')

from app.core.tsf_hook import TsfHook

events = []
hk = TsfHook(on_commit=lambda t: events.append(('commit', t)),
             on_composing=lambda f: events.append(('composing', f)))
ok = hk.start()
print('TSF available:', ok)
time.sleep(1.5)
print('TSF active:', hk.active, '| composing:', hk.composing)
hk.stop()
print('thread stopped:', not hk._thread.is_alive())
print('events:', events)
print('TSF 冒烟:', 'PASS' if ok else 'FAIL')
