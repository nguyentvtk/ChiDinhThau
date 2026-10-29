@echo off
chcp 65001 >nul
title Khởi chạy Ứng dụng Quản lý Chỉ định thầu - Ban QLDA Xã Tân Phú
echo =====================================================================
echo    HỆ THỐNG SOẠN THẢO VÀ QUẢN LÝ HỒ SƠ CHỈ ĐỊNH THẦU PRO v1.0
echo    Ban Quản lý Dự án Đầu tư Xây dựng Xã Tân Phú
echo =====================================================================
echo.
echo Đang mở giao diện trên trình duyệt web mặc định...
start "" "%~dp0index.html"
echo.
echo Đã khởi động ứng dụng thành công!
exit
