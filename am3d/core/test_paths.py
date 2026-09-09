"""Cross-platform path policy regression tests (finding ENV-03).

The bug these guard against: `os.path.splitdrive("D:out")` returns
`("", "D:out")` on POSIX, so a Windows drive-relative export path passed the
recipe executor's escape check on Linux and was rejected on Windows. A recipe
is a portable document; the verdict must not depend on the host OS.
"""

import os

import pytest

from am3d.core.paths import (classify_portable_relative_path,
                             has_drive_letter, has_traversal,
                             is_absolute_any_platform, is_unc,
                             normalize_separators, reserved_component,
                             split_segments)


@pytest.mark.parametrize("path", [
    "D:outside_file",     # drive-RELATIVE: the case that regressed
    "D:\\outside_file",
    "c:/outside_file",
    "Z:",
])
def test_windows_drive_paths_rejected_on_every_platform(path):
    assert has_drive_letter(path)
    verdict = classify_portable_relative_path(path)
    assert verdict is not None
    assert "drive letter" in verdict[0]


@pytest.mark.parametrize("path", ["\\\\server\\share\\f.obj", "//server/share/f.obj"])
def test_unc_paths_rejected(path):
    assert is_unc(path)
    assert "UNC" in classify_portable_relative_path(path)[0]


@pytest.mark.parametrize("path", ["/etc/passwd", "\\windows\\system32\\f.obj"])
def test_absolute_paths_rejected(path):
    assert is_absolute_any_platform(path)
    assert classify_portable_relative_path(path) is not None


@pytest.mark.parametrize("path", [
    "../outside.obj", "..\\outside.obj", "sub/../../outside.obj",
    "sub\\..\\..\\outside.obj",
])
def test_traversal_rejected_with_either_separator(path):
    assert has_traversal(path)
    assert "'..'" in classify_portable_relative_path(path)[0]


@pytest.mark.parametrize("path", [".", "./", ".\\", "", "   "])
def test_non_file_paths_rejected(path):
    assert classify_portable_relative_path(path) is not None


@pytest.mark.parametrize("path", ["NUL.obj", "sub/CON.obj", "com1.obj"])
def test_windows_reserved_device_names_rejected(path):
    assert reserved_component(path) is not None
    assert "reserved device name" in classify_portable_relative_path(path)[0]


@pytest.mark.parametrize("path", ["a?b.obj", "a<b.obj", 'a"b.obj', "a|b.obj"])
def test_windows_invalid_characters_rejected(path):
    assert "invalid on Windows" in classify_portable_relative_path(path)[0]


@pytest.mark.parametrize("path", [
    "out.obj",
    "sub/out.obj",
    "sub\\out.obj",              # accepted, and normalised to a subdirectory
    "ünïcødé.obj",               # legitimate Unicode must NOT be rejected
    "日本語/モデル.obj",
    "Ω-mesh_v2.final.obj",
    "with space/my model.obj",
])
def test_legitimate_relative_paths_accepted(path):
    assert classify_portable_relative_path(path) is None


def test_backslash_is_a_separator_not_a_filename_character():
    # Same recipe, same directory structure, on either host.
    assert split_segments("sub\\out.obj") == ["sub", "out.obj"]
    assert normalize_separators("sub\\out.obj") == os.path.join("sub", "out.obj")


def test_is_absolute_any_platform_accepts_relative_names():
    for rel in ("out.obj", "sub/out.obj", "D:rel"):
        # "D:rel" is drive-relative, i.e. not absolute -- it is rejected by
        # the drive-letter rule instead, not by the absoluteness rule.
        assert not is_absolute_any_platform(rel)
