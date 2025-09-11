@echo off
chcp 1251
cls
REM Path to parser.py (set absolute path!)
set PARSER_PATH="D:\Program files\myProjects\Parser\parser.py"
REM Run from the current folder where this bat is located
python %PARSER_PATH%
pause