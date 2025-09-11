@echo off
chcp 1251
cls
REM Path to gui.py (set absolute path!)
set GUI_PATH="D:\Program files\myProjects\Parser\gui.py"
REM Run GUI from the current folder where this bat is located
start "" /B pythonw %GUI_PATH%
exit
