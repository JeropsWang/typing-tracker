"""在 Qt 导入前锁定 Windows ICU，避免打包环境中同名第三方 DLL 抢占。"""
import ctypes
import os

if os.name == 'nt':
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetSystemDirectoryW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint]
    kernel.GetSystemDirectoryW.restype = ctypes.c_uint
    directory = ctypes.create_unicode_buffer(32768)
    length = kernel.GetSystemDirectoryW(directory, len(directory))
    if 0 < length < len(directory):
        icu = os.path.join(directory.value, 'icuuc.dll')
        if os.path.isfile(icu):
            _system_icu = ctypes.WinDLL(icu)
