# The desktop shell

`clean_shell.py` is the window the founder opens: the Qt shell -- icon, title,
taskbar identity, persistent profile -- pointed at the clean owner's canvas on
127.0.0.1:8475.

It ran only from `%LOCALAPPDATA%\ArchHub\app\clean_shell.py` and existed
nowhere else, so the app the founder actually uses could not be reviewed,
diffed, or restored. This is the source of record; the installed copy is the
deployment of it.

To deploy a change:

    copy desktop\clean_shell.py %LOCALAPPDATA%\ArchHub\app\clean_shell.py

The launchers next to it (`ArchHub-Clean.cmd`, `ArchHub-Clean.vbs`) start this
file with the machine's pythoncore interpreter.
