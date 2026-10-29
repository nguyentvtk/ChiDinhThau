@echo off
chcp 65001 >nul
title TRA CUU NHA THAU - MUASAMCONG.MPI.GOV.VN
cd /d "%~dp0"
python "%~dp0tra_cuu_muasamcong.py"
if errorlevel 1 pause
