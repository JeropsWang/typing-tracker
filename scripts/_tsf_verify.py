"""TSF 技术验证：comtypes 生成 msctf 绑定 + 创建线程管理器 + 激活。

如果这步成功，说明 TSF 路线可行（组字监听在此基础上实现）。
"""
import sys
import time

sys.path.insert(0, r'D:\dz\typing-tracker\.deps')
sys.path.insert(0, r'D:\dz\typing-tracker')

import ctypes
from comtypes import COMObject, CoClass, GUID, IUnknown, c_void_p, HRESULT
from comtypes.client import GetModule
import comtypes

print('comtypes', comtypes.__version__)

# 1) 生成 msctf 绑定（TSF 接口定义）
GetModule('msctf')
import comtypes.gen.MSCTF as MSCTF
print('MSCTF 绑定生成成功')

# 关键接口
for name in ['ITfThreadMgr', 'ITfSource', 'ITfDocumentMgr', 'ITfContext',
             'ITfContextComposition', 'ITfCompositionView', 'ITfRange',
             'ITfThreadMgrEventSink', 'ITfTextEditSink']:
    print(' ', name, hasattr(MSCTF, name))

CLSID_TF_ThreadMgr = GUID('{529A9E6B-6587-4F23-AB9E-9C7D683E3C50}')
IID_ITfThreadMgr = GUID('{AA80E801-2021-11D2-93E0-0060B067B86E}')

# 2) 创建线程管理器并激活（COM STA）
comtypes.CoInitialize()
try:
    mgr = comtypes.CoCreateInstance(CLSID_TF_ThreadMgr, interface=MSCTF.ITfThreadMgr)
    print('ITfThreadMgr 创建成功')
    hr = mgr.Activate()
    print('Activate hr =', hex(hr & 0xFFFFFFFF) if hr < 0 else hr)
    hr2 = mgr.Deactivate()
    print('Deactivate hr =', hr2)
finally:
    comtypes.CoUninitialize()
print('TSF 基础验证 PASS')
