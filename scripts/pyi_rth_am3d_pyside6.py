# -----------------------------------------------------------------------------
# Copyright (c) 2021-2023, PyInstaller Development Team.
#
# This file retains the PyInstaller PySide6 runtime hook behavior.
# Licensed under the Apache License, Version 2.0 (the "License");
# see the upstream COPYING.txt notice distributed with the application.
# SPDX-License-Identifier: Apache-2.0
# -----------------------------------------------------------------------------

"""PySide6 setup hook that leaves fixed Qt-free entry paths untouched.

The normal GUI setup below follows PyInstaller's pyi_rth_pyside6 hook. Fixed
AI worker and offline acceptance entry points must reach the application's
pre-Qt dispatch before PySide6 is imported, so those argv forms skip Qt
initialization here.
"""


def _pyi_rthook():
    import sys

    if (len(sys.argv) > 1 and sys.argv[1] in {
            "--internal-ai-worker", "--am3d-generation-worker", "--ai-self-test"}):
        return

    import os

    from _pyi_rth_utils import is_macos_app_bundle, prepend_path_to_environment_variable
    from _pyi_rth_utils import qt as qt_rth_utils

    # Ensure this is the only Qt bindings package in the application.
    qt_rth_utils.ensure_single_qt_bindings_package("PySide6")

    if sys.platform.startswith("win"):
        pyqt_path = os.path.join(sys._MEIPASS, "PySide6")
    else:
        pyqt_path = os.path.join(sys._MEIPASS, "PySide6", "Qt")

    os.environ["QT_PLUGIN_PATH"] = os.path.join(pyqt_path, "plugins")

    if is_macos_app_bundle:
        # Special handling for macOS .app bundles. To satisfy codesign
        # requirements, the QML tree is split between Frameworks and Resources.
        pyqt_path_res = os.path.normpath(
            os.path.join(sys._MEIPASS, "..", "Resources", os.path.relpath(pyqt_path, sys._MEIPASS))
        )
        os.environ["QML2_IMPORT_PATH"] = os.pathsep.join([
            os.path.join(pyqt_path_res, "qml"),
            os.path.join(pyqt_path, "qml"),
        ])
    else:
        os.environ["QML2_IMPORT_PATH"] = os.path.join(pyqt_path, "qml")

    # Add sys._MEIPASS to PATH so QtNetwork can find collected OpenSSL DLLs.
    if sys.platform.startswith("win"):
        prepend_path_to_environment_variable(sys._MEIPASS, "PATH")

    # Keep the QtNetwork TLS lookup isolated from external locations on macOS.
    if sys.platform == "darwin" and not is_macos_app_bundle:
        prepend_path_to_environment_variable(sys._MEIPASS, "DYLD_LIBRARY_PATH")

    # PySide6 wheels usually create qt.conf during initialization. For
    # installations that do not, reproduce PyInstaller's fallback behavior.
    qt_rth_utils.create_embedded_qt_conf("PySide6", pyqt_path)


_pyi_rthook()
del _pyi_rthook
