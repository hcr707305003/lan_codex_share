import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
pytest.importorskip('PySide6')
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog
from lan_codex_share.desktop.dialogs import StopDialog


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize('key', [Qt.Key_Return, Qt.Key_Escape])
def test_default_keys_cancel(app, key):
    dialog = StopDialog(None, 'frpc')
    dialog.show()
    app.processEvents()
    assert dialog.cancel.isDefault()
    assert not dialog.confirm.isDefault()
    QTest.keyClick(dialog, key)
    assert dialog.result() == QDialog.Rejected
    assert not dialog.isVisible()


@pytest.mark.parametrize('force', [True, False])
def test_explicit_confirmation_and_wrapping(app, force):
    dialog = StopDialog(None, 'Share', force=force, details='PID 1234\n' + 'long-path/' * 40)
    dialog.show()
    app.processEvents()
    assert dialog.detail.wordWrap()
    assert dialog.detail.textFormat() == Qt.PlainText
    assert dialog.detail.height() >= dialog.detail.heightForWidth(dialog.detail.width())
    assert 'Share' in dialog.windowTitle()
    assert dialog.confirm.text() == ('强制关闭' if force else '停止服务')
    dialog.confirm.click()
    assert dialog.result() == QDialog.Accepted
