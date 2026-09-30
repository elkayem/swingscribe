"""QuickEdit is off while the app runs and back as it was afterwards."""

import pytest

from swingscribe import console

QUICK_EDIT = console.ENABLE_QUICK_EDIT_MODE
EXTENDED = console.ENABLE_EXTENDED_FLAGS


class FakeKernel32:
    """The three console calls, over one input mode."""

    def __init__(self, mode, is_console=True):
        self.mode = mode
        self.is_console = is_console
        self.set_calls = []

    def GetStdHandle(self, which):
        assert which == console.STD_INPUT_HANDLE
        return 7

    def GetConsoleMode(self, handle, mode_ptr):
        if not self.is_console:
            return 0
        mode_ptr.contents.value = self.mode
        return 1

    def SetConsoleMode(self, handle, mode):
        self.set_calls.append(mode)
        self.mode = mode
        return 1


def test_quick_edit_is_off_inside_and_restored_after():
    # 0x1f7 is the mode the icon's console reported on 2026-09-29.
    kernel32 = FakeKernel32(0x1F7)
    with console.quick_edit_disabled(kernel32):
        assert not kernel32.mode & QUICK_EDIT
        assert kernel32.mode & EXTENDED
        assert kernel32.mode | QUICK_EDIT == 0x1F7  # nothing else touched
    assert kernel32.mode == 0x1F7


def test_restored_when_the_app_exits_through_systemexit():
    kernel32 = FakeKernel32(0x1F7)
    with pytest.raises(SystemExit), console.quick_edit_disabled(kernel32):
        raise SystemExit(0)
    assert kernel32.mode == 0x1F7


def test_restore_carries_the_extended_flag_so_the_bit_is_honoured():
    kernel32 = FakeKernel32(QUICK_EDIT | 0x7)
    with console.quick_edit_disabled(kernel32):
        pass
    assert kernel32.set_calls[-1] == QUICK_EDIT | EXTENDED | 0x7


def test_stdin_that_is_not_a_console_is_left_alone():
    kernel32 = FakeKernel32(0x1F7, is_console=False)
    with console.quick_edit_disabled(kernel32):
        pass
    assert kernel32.set_calls == []


def test_quick_edit_already_off_is_left_alone():
    kernel32 = FakeKernel32(0x1B7)
    with console.quick_edit_disabled(kernel32):
        pass
    assert kernel32.set_calls == []


def test_real_platform_call_never_raises():
    # Under pytest stdin is rarely a console (CI never): a no-op there, and
    # on Linux no kernel32 is touched at all.
    with console.quick_edit_disabled():
        pass
