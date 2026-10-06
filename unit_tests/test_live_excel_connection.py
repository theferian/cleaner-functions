from __future__ import annotations

from cleaner_core.live_excel import _workbooks_collection, _fresh_excel_application


class _AppOnly:
    def __init__(self, workbooks):
        self.Application = type("Application", (), {"Workbooks": workbooks})()

    @property
    def Workbooks(self):
        raise AttributeError("dynamic COM wrapper has no Workbooks")


def test_workbooks_collection_falls_back_through_application():
    marker = object()
    assert _workbooks_collection(_AppOnly(marker)) is marker


class _BadActive:
    @property
    def Workbooks(self):
        raise AttributeError("bad active wrapper")

    @property
    def Application(self):
        raise AttributeError("bad active wrapper")


class _HealthyExcel:
    Workbooks = object()


class _Client:
    def __init__(self):
        self.calls = []

    def DispatchEx(self, progid):
        self.calls.append(("DispatchEx", progid))
        return _HealthyExcel()


def test_fresh_excel_prefers_dispatch_ex():
    client = _Client()
    excel = _fresh_excel_application(client)
    assert isinstance(excel, _HealthyExcel)
    assert client.calls == [("DispatchEx", "Excel.Application")]
