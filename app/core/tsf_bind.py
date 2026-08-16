"""TSF（Text Services Framework）COM 接口绑定（comtypes 手写定义）。

方法顺序严格按 Windows SDK msctf.idl（10.0.22621.0），未使用的方法
用简化签名占位（vtable 槽位顺序不变，签名只影响 Python 侧包装）。
"""
from __future__ import annotations

from ctypes import POINTER, c_long, c_ulong, c_void_p, c_wchar

from comtypes import COMMETHOD, GUID, HRESULT, IUnknown

# ---- 类型别名 ----
TfClientId = c_ulong
TfEditCookie = c_ulong

P_UNK = POINTER(c_void_p)     # IUnknown* / 任意接口指针
PP = POINTER(P_UNK)           # void**

# ---- 常量 ----
TF_ES_SYNC = 0x1
TF_ES_READ = 0x2
TF_ES_READWRITE = 0x6
TF_ES_ASYNC = 0x8
TF_EC_NULL = 0

CLSID_TF_ThreadMgr = GUID('{529A9E6B-6587-4F23-AB9E-9C7D683E3C50}')
IID_ITfThreadMgrEventSink = GUID('{aa80e80e-2021-11d2-93e0-0060b067b86e}')
IID_ITfTextEditSink = GUID('{7A80F2C0-1884-45A1-B59E-AC965E4D3D40}')


class ITfThreadMgr(IUnknown):
    _iid_ = GUID('{aa80e801-2021-11d2-93e0-0060b067b86e}')
    _methods_ = [
        COMMETHOD([], HRESULT, 'Activate', (['in'], POINTER(TfClientId), 'ptid')),
        COMMETHOD([], HRESULT, 'Deactivate'),
        COMMETHOD([], HRESULT, 'CreateDocumentMgr', (['in'], PP, 'ppdim')),
        COMMETHOD([], HRESULT, 'EnumDocumentMgrs', (['in'], PP, 'ppEnum')),
        COMMETHOD([], HRESULT, 'GetFocus', (['in'], PP, 'ppdimFocus')),
        COMMETHOD([], HRESULT, 'SetFocus', (['in'], P_UNK, 'pdimFocus')),
        COMMETHOD([], HRESULT, 'AssociateFocus', (['in'], c_void_p, 'hwnd'),
                  (['in'], P_UNK, 'pdimNew'), (['in'], PP, 'ppdimPrev')),
        COMMETHOD([], HRESULT, 'IsThreadFocus', (['in'], POINTER(c_ulong), 'pfThreadFocus')),
        COMMETHOD([], HRESULT, 'GetFunctionProvider', (['in'], POINTER(GUID), 'clsid'),
                  (['in'], PP, 'ppFuncProv')),
        COMMETHOD([], HRESULT, 'EnumFunctionProviders', (['in'], PP, 'ppEnum')),
        COMMETHOD([], HRESULT, 'GetGlobalCompartment', (['in'], PP, 'ppCompMgr')),
    ]


class ITfThreadMgrEventSink(IUnknown):
    _iid_ = GUID('{aa80e80e-2021-11d2-93e0-0060b067b86e}')
    _methods_ = [
        COMMETHOD([], HRESULT, 'OnInitDocumentMgr', (['in'], P_UNK, 'pdim')),
        COMMETHOD([], HRESULT, 'OnUninitDocumentMgr', (['in'], P_UNK, 'pdim')),
        COMMETHOD([], HRESULT, 'OnSetFocus', (['in'], P_UNK, 'pdimFocus'),
                  (['in'], P_UNK, 'pdimPrevFocus')),
        COMMETHOD([], HRESULT, 'OnPushContext', (['in'], P_UNK, 'pic')),
        COMMETHOD([], HRESULT, 'OnPopContext', (['in'], P_UNK, 'pic')),
    ]


class ITfDocumentMgr(IUnknown):
    _iid_ = GUID('{aa80e7f4-2021-11d2-93e0-0060b067b86e}')
    _methods_ = [
        COMMETHOD([], HRESULT, 'CreateContext', (['in'], TfClientId, 'tidOwner'),
                  (['in'], c_ulong, 'dwFlags'), (['in'], P_UNK, 'punk'),
                  (['in'], PP, 'ppic'), (['in'], POINTER(TfEditCookie), 'pecTextStore')),
        COMMETHOD([], HRESULT, 'Push', (['in'], P_UNK, 'pic')),
        COMMETHOD([], HRESULT, 'Pop', (['in'], c_ulong, 'dwFlags')),
        COMMETHOD([], HRESULT, 'GetTop', (['in'], PP, 'ppic')),
        COMMETHOD([], HRESULT, 'GetBase', (['in'], PP, 'ppic')),
        COMMETHOD([], HRESULT, 'EnumContexts', (['in'], PP, 'ppEnum')),
    ]


class ITfContext(IUnknown):
    _iid_ = GUID('{aa80e7fd-2021-11d2-93e0-0060b067b86e}')
    _methods_ = [
        COMMETHOD([], HRESULT, 'RequestEditSession', (['in'], TfClientId, 'tid'),
                  (['in'], P_UNK, 'pes'), (['in'], c_ulong, 'dwFlags'),
                  (['out'], POINTER(HRESULT), 'phrSession')),
        COMMETHOD([], HRESULT, 'InWriteSession', (['in'], TfClientId, 'tid'),
                  (['out'], POINTER(c_ulong), 'pfWriteSession')),
        COMMETHOD([], HRESULT, 'GetSelection', (['in'], TfEditCookie, 'ec'),
                  (['in'], c_ulong, 'ulIndex'), (['in'], c_ulong, 'ulCount'),
                  (['in'], P_UNK, 'pSelection'), (['out'], POINTER(c_ulong), 'pcFetched')),
        COMMETHOD([], HRESULT, 'SetSelection', (['in'], TfEditCookie, 'ec'),
                  (['in'], c_ulong, 'ulCount'), (['in'], P_UNK, 'pSelection')),
        COMMETHOD([], HRESULT, 'GetStart', (['in'], TfEditCookie, 'ec'),
                  (['out'], PP, 'ppStart')),
        COMMETHOD([], HRESULT, 'GetEnd', (['in'], TfEditCookie, 'ec'),
                  (['out'], PP, 'ppEnd')),
        COMMETHOD([], HRESULT, 'GetActiveView', (['out'], PP, 'ppView')),
        COMMETHOD([], HRESULT, 'EnumViews', (['out'], PP, 'ppEnum')),
        COMMETHOD([], HRESULT, 'GetStatus', (['out'], P_UNK, 'pdcs')),
        COMMETHOD([], HRESULT, 'GetProperty', (['in'], POINTER(GUID), 'guidProp'),
                  (['out'], PP, 'ppProp')),
        COMMETHOD([], HRESULT, 'GetAppProperty', (['in'], POINTER(GUID), 'guidProp'),
                  (['out'], PP, 'ppProp')),
        COMMETHOD([], HRESULT, 'TrackProperties', (['in'], P_UNK, 'prgProp'),
                  (['in'], c_ulong, 'cProp'), (['in'], P_UNK, 'prgAppProp'),
                  (['in'], c_ulong, 'cAppProp'), (['out'], PP, 'ppProperty')),
        COMMETHOD([], HRESULT, 'EnumProperties', (['out'], PP, 'ppEnum')),
        COMMETHOD([], HRESULT, 'GetDocumentMgr', (['out'], PP, 'ppDm')),
        COMMETHOD([], HRESULT, 'CreateRangeBackup', (['in'], TfEditCookie, 'ec'),
                  (['in'], P_UNK, 'pRange'), (['out'], PP, 'ppBackup')),
    ]


class ITfContextComposition(IUnknown):
    _iid_ = GUID('{D40C8AAE-AC92-4FC7-9A11-0EE0E23AA39B}')
    _methods_ = [
        COMMETHOD([], HRESULT, 'StartComposition', (['in'], TfEditCookie, 'ecWrite'),
                  (['in'], P_UNK, 'pCompositionRange'), (['in'], P_UNK, 'pSink'),
                  (['in'], PP, 'ppComposition')),
        COMMETHOD([], HRESULT, 'EnumCompositions', (['in'], PP, 'ppEnum')),
        COMMETHOD([], HRESULT, 'FindComposition', (['in'], TfEditCookie, 'ecRead'),
                  (['in'], P_UNK, 'pTestRange'), (['in'], PP, 'ppEnum')),
        COMMETHOD([], HRESULT, 'TakeOwnership', (['in'], TfEditCookie, 'ecWrite'),
                  (['in'], P_UNK, 'pComposition'), (['in'], P_UNK, 'pSink'),
                  (['in'], PP, 'ppComposition')),
    ]


class IEnumITfCompositionView(IUnknown):
    _iid_ = GUID('{5EFD22BA-7838-46CB-88E2-CADB14124F8F}')
    _methods_ = [
        COMMETHOD([], HRESULT, 'Clone', (['in'], PP, 'ppEnum')),
        COMMETHOD([], HRESULT, 'Next', (['in'], c_ulong, 'ulCount'),
                  (['in'], POINTER(P_UNK), 'rgView'),
                  (['in'], POINTER(c_ulong), 'pcFetched')),
        COMMETHOD([], HRESULT, 'Reset'),
        COMMETHOD([], HRESULT, 'Skip', (['in'], c_ulong, 'ulCount')),
    ]


class ITfCompositionView(IUnknown):
    _iid_ = GUID('{D7540241-F9A1-4364-BEFC-DBCD2C4395B7}')
    _methods_ = [
        COMMETHOD([], HRESULT, 'GetOwnerClsid', (['in'], POINTER(GUID), 'pclsid')),
        COMMETHOD([], HRESULT, 'GetRange', (['in'], PP, 'ppRange')),
    ]


class ITfRange(IUnknown):
    _iid_ = GUID('{aa80e7ff-2021-11d2-93e0-0060b067b86e}')
    _methods_ = [
        COMMETHOD([], HRESULT, 'GetText', (['in'], TfEditCookie, 'ec'),
                  (['in'], c_ulong, 'dwFlags'), (['in'], POINTER(c_wchar), 'pchText'),
                  (['in'], c_ulong, 'cchMax'), (['in'], POINTER(c_ulong), 'pcch')),
        COMMETHOD([], HRESULT, 'SetText', (['in'], TfEditCookie, 'ec'),
                  (['in'], c_ulong, 'dwFlags'), (['in'], POINTER(c_wchar), 'pchText'),
                  (['in'], c_long, 'cch')),
        COMMETHOD([], HRESULT, 'GetFormattedText', (['in'], TfEditCookie, 'ec'),
                  (['out'], PP, 'ppDataObject')),
        COMMETHOD([], HRESULT, 'GetEmbedded', (['in'], TfEditCookie, 'ec'),
                  (['in'], POINTER(GUID), 'rguidService'), (['in'], POINTER(GUID), 'riid'),
                  (['out'], PP, 'ppunk')),
        COMMETHOD([], HRESULT, 'InsertEmbedded', (['in'], TfEditCookie, 'ec'),
                  (['in'], c_ulong, 'dwFlags'), (['in'], P_UNK, 'pDataObject')),
        COMMETHOD([], HRESULT, 'ShiftStart', (['in'], TfEditCookie, 'ec'),
                  (['in'], c_long, 'cchReq'), (['out'], POINTER(c_long), 'pcch'),
                  (['in'], P_UNK, 'pHalt')),
        COMMETHOD([], HRESULT, 'ShiftEnd', (['in'], TfEditCookie, 'ec'),
                  (['in'], c_long, 'cchReq'), (['out'], POINTER(c_long), 'pcch'),
                  (['in'], P_UNK, 'pHalt')),
        COMMETHOD([], HRESULT, 'ShiftStartToRange', (['in'], TfEditCookie, 'ec'),
                  (['in'], P_UNK, 'pRange'), (['in'], c_long, 'aPos')),
        COMMETHOD([], HRESULT, 'ShiftEndToRange', (['in'], TfEditCookie, 'ec'),
                  (['in'], P_UNK, 'pRange'), (['in'], c_long, 'aPos')),
        COMMETHOD([], HRESULT, 'ShiftStartRegion', (['in'], TfEditCookie, 'ec'),
                  (['in'], c_ulong, 'dir'), (['out'], POINTER(c_ulong), 'pfNoRegion')),
        COMMETHOD([], HRESULT, 'ShiftEndRegion', (['in'], TfEditCookie, 'ec'),
                  (['in'], c_ulong, 'dir'), (['out'], POINTER(c_ulong), 'pfNoRegion')),
        COMMETHOD([], HRESULT, 'IsEmpty', (['in'], TfEditCookie, 'ec'),
                  (['out'], POINTER(c_ulong), 'pfEmpty')),
        COMMETHOD([], HRESULT, 'Collapse', (['in'], TfEditCookie, 'ec'),
                  (['in'], c_long, 'aPos')),
        COMMETHOD([], HRESULT, 'IsEqualStart', (['in'], TfEditCookie, 'ec'),
                  (['in'], P_UNK, 'pWith'), (['in'], c_long, 'aPos'),
                  (['out'], POINTER(c_ulong), 'pfEqual')),
        COMMETHOD([], HRESULT, 'IsEqualEnd', (['in'], TfEditCookie, 'ec'),
                  (['in'], P_UNK, 'pWith'), (['in'], c_long, 'aPos'),
                  (['out'], POINTER(c_ulong), 'pfEqual')),
        COMMETHOD([], HRESULT, 'CompareStart', (['in'], TfEditCookie, 'ec'),
                  (['in'], P_UNK, 'pWith'), (['in'], c_long, 'aPos'),
                  (['out'], POINTER(c_long), 'plResult')),
        COMMETHOD([], HRESULT, 'CompareEnd', (['in'], TfEditCookie, 'ec'),
                  (['in'], P_UNK, 'pWith'), (['in'], c_long, 'aPos'),
                  (['out'], POINTER(c_long), 'plResult')),
        COMMETHOD([], HRESULT, 'AdjustForInsert', (['in'], TfEditCookie, 'ec'),
                  (['in'], c_ulong, 'cchInsert'), (['out'], POINTER(c_ulong), 'pfInsertOk')),
        COMMETHOD([], HRESULT, 'GetGravity', (['out'], POINTER(c_long), 'pgStart'),
                  (['out'], POINTER(c_long), 'pgEnd')),
        COMMETHOD([], HRESULT, 'SetGravity', (['in'], TfEditCookie, 'ec'),
                  (['in'], c_long, 'gStart'), (['in'], c_long, 'gEnd')),
        COMMETHOD([], HRESULT, 'Clone', (['out'], PP, 'ppClone')),
        COMMETHOD([], HRESULT, 'GetContext', (['out'], PP, 'ppContext')),
    ]


class ITfSource(IUnknown):
    _iid_ = GUID('{4EA48A35-60AE-446F-8FD6-E6A8D82459F7}')
    _methods_ = [
        COMMETHOD([], HRESULT, 'AdviseSink', (['in'], POINTER(GUID), 'riid'),
                  (['in'], P_UNK, 'punk'), (['in'], POINTER(c_ulong), 'pdwCookie')),
        COMMETHOD([], HRESULT, 'UnadviseSink', (['in'], c_ulong, 'dwCookie')),
    ]


class ITfEditSession(IUnknown):
    _iid_ = GUID('{1A8FE1F2-7590-4E33-8E16-ED9E952DE89B}')
    _methods_ = [
        COMMETHOD([], HRESULT, 'DoEditSession', (['in'], TfEditCookie, 'ec')),
    ]
