# Desktop third-party components

The desktop distribution uses Python, PySide6 / Qt 6.11.2, Shiboken, tomlkit,
PyYAML and the dependencies of the existing Share executable.

PySide6 / Shiboken and the Qt modules used by this application are distributed
under their applicable open-source license options. License texts collected from
the dependency distributions and Qt's versioned source are included in the GUI
runtime's `licenses` directory. Inclusion of a commercial-license reference in
an upstream wheel does not mean this project grants a Qt commercial license.

The GUI is dynamically linked to Qt in a directory-style distribution. The Qt
libraries remain separate files; this application imposes no restriction on
replacement of those libraries or reverse engineering needed to debug changes
to LGPL-covered components. Keep the license texts with redistributed copies.

Corresponding upstream source and notices:

- Qt: <https://github.com/qt/qtbase/tree/v6.11.2>
- PySide6 / Shiboken: <https://github.com/qt/pyside-setup/tree/v6.11.2>
- Qt third-party component notices: <https://doc.qt.io/qt-6/licenses-used-in-qt.html>
- CPython: <https://www.python.org/downloads/source/>
- tomlkit: <https://github.com/python-poetry/tomlkit>
- PyYAML: <https://github.com/yaml/pyyaml>

frpc and cloudflared are not embedded in this GUI archive. If downloaded or
installed separately, their own distributions and licenses apply. Review all
applicable third-party notices before redistributing modified binaries.
