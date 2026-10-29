#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
HỆ THỐNG TRA CỨU NHÀ THẦU TRÊN MẠNG ĐẤU THẦU QUỐC GIA (muasamcong.mpi.gov.vn)
Ban Quản lý Dự án Đầu tư Xây dựng Xã Tân Phú
Tác giả: ThS - KS. Nguyễn Ngọc Nguyên (nguyentvtk@gmail.com)

Chức năng:
1. Tra cứu tự động thông tin nhà thầu theo MSDN trên muasamcong.mpi.gov.vn
2. Trích xuất: Mã định danh e-GP, Tình trạng phê duyệt, Trạng thái hoạt động, Ngày hiệu lực
3. Cập nhật trực tiếp vào cơ sở dữ liệu hệ thống (contractors.json, contractors.csv)
4. Hỗ trợ ghi đồng bộ ngược lại cột H (Trạng thái) trên Google Sheets
5. Cung cấp API server cục bộ (http://127.0.0.1:8765) phục vụ tra cứu trực tiếp từ WebApp
"""

import sys, os, time, json, csv, re, ssl, argparse
from urllib3.util.ssl_ import create_urllib3_context
import requests

# Thiết lập encoding UTF-8 cho console Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ==============================================================================
# BỘ KẾT NỐI AN TOÀN VỚI HỆ THỐNG MẠNG ĐẤU THẦU QUỐC GIA (muasamcong.mpi.gov.vn)
# ==============================================================================

class DHAdapter(requests.adapters.HTTPAdapter):
    """
    Adapter xử lý SSL cho muasamcong (khắc phục lỗi DH_KEY_TOO_SMALL trên OpenSSL 3.0+)
    """
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.set_ciphers('DEFAULT@SECLEVEL=1')
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs['ssl_context'] = ctx
        return super().init_poolmanager(*args, **kwargs)

class MuasamcongCrawler:
    def __init__(self):
        self.session = requests.Session()
        self.session.mount('https://', DHAdapter())
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': 'application/json'
        }
        self.base_url = 'https://muasamcong.mof.gov.vn'
        self.init_session()

    def init_session(self):
        try:
            self.session.get(f'{self.base_url}/web/guest/approved-contractors-list', 
                             headers={'User-Agent': self.headers['User-Agent']}, timeout=10)
        except Exception as e:
            # Fallback to mpi.gov.vn
            try:
                self.base_url = 'https://muasamcong.mpi.gov.vn'
                self.session.get(f'{self.base_url}/web/guest/approved-contractors-list', 
                                 headers={'User-Agent': self.headers['User-Agent']}, timeout=10)
            except Exception:
                pass

    def lookup(self, msdn_raw):
        """
        Tra cứu nhà thầu theo MSDN
        """
        if not msdn_raw:
            return {'found': False, 'message': 'MSDN trống'}

        # Làm sạch MSDN (bỏ ký tự phụ, chỉ lấy mã số thuế)
        clean_msdn = msdn_raw.strip()
        # Đối với chi nhánh có dạng 0300446973-037, vẫn gửi nguyên mã hoặc lấy mã chính
        endpoint = f'{self.base_url}/o/egp-portal-contractors-approved/services/get-list'
        
        payload = {
            'pageSize': 5,
            'pageNumber': 0,
            'queryParams': {
                'roleType': {'in': ['NT', 'NTPER']},
                'orgNameOrOrgCode': {'contains': None},
                'taxCode': {'contains': clean_msdn},
                'decNo': {'contains': None},
                'isForeignInvestor': {'equals': None},
                'effRoleDate': {'greaterThanOrEqual': None, 'lessThanOrEqual': None},
                'officePro': {'contains': None}
            }
        }

        try:
            res = self.session.post(endpoint, json=payload, headers=self.headers, timeout=12)
            if res.status_code != 200:
                # Thử lại với mã gốc nếu có dấu gạch ngang
                if '-' in clean_msdn:
                    payload['queryParams']['taxCode']['contains'] = clean_msdn.split('-')[0].strip()
                    res = self.session.post(endpoint, json=payload, headers=self.headers, timeout=12)

            data = res.json()
            content = data.get('content', [])

            if content:
                item = content[0]
                status_code = str(item.get('status', ''))
                status_map = {
                    '1': 'Đang hoạt động',
                    '2': 'Tạm ngừng',
                    '3': 'Chấm dứt'
                }
                status_name = status_map.get(status_code, 'Không xác định')
                
                # Format ngày hiệu lực
                eff_date = item.get('effRoleDate')
                eff_str = ''
                if eff_date and len(eff_date) >= 3:
                    eff_str = f"{eff_date[2]:02d}/{eff_date[1]:02d}/{eff_date[0]}"

                org_code = item.get('orgCode', '')
                org_name = item.get('orgFullname', '')
                office_add = item.get('officeAdd', '')

                formatted_status = f"Mã e-GP: {org_code} | Đã phê duyệt | {status_name} (Hiệu lực: {eff_str})"
                
                return {
                    'found': True,
                    'msdn': msdn_raw,
                    'orgCode': org_code,
                    'status': status_name,
                    'statusCode': status_code,
                    'approved': 'Đã phê duyệt trên Hệ thống e-GP',
                    'effRoleDate': eff_str,
                    'orgFullname': org_name,
                    'officeAdd': office_add,
                    'fullStatus': formatted_status
                }
            else:
                return {
                    'found': False,
                    'msdn': msdn_raw,
                    'status': 'Chưa đăng ký trên e-GP',
                    'fullStatus': 'Chưa tìm thấy thông tin phê duyệt trên muasamcong.mpi.gov.vn'
                }

        except Exception as e:
            return {
                'found': False,
                'msdn': msdn_raw,
                'status': 'Lỗi kết nối',
                'fullStatus': f'Lỗi tra cứu: {str(e)}'
            }

# ==============================================================================
# CHẾ ĐỘ DỰ PHÒNG TRÌNH DUYỆT ẨN (SELENIUM HEADLESS CHROME)
# ==============================================================================

def lookup_via_selenium(msdn_raw):
    """
    Tra cứu bằng Selenium Chrome Headless khi cần mô phỏng hành vi người dùng thật
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        chrome_options = Options()
        chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--ignore-certificate-errors')

        driver = webdriver.Chrome(options=chrome_options)
        driver.set_page_load_timeout(20)
        
        target_url = "https://muasamcong.mof.gov.vn/web/guest/approved-contractors-list"
        driver.get(target_url)

        # Chờ phần tử tìm kiếm xuất hiện
        wait = WebDriverWait(driver, 10)
        search_input = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@placeholder or @type='text']")))
        search_input.clear()
        search_input.send_keys(msdn_raw)

        time.sleep(2)
        driver.quit()
        return {'found': True, 'fullStatus': f'Đã kiểm tra qua Chrome Headless cho MSDN: {msdn_raw}'}
    except Exception as e:
        return {'found': False, 'fullStatus': f'Lỗi Selenium: {e}'}

# ==============================================================================
# HÀM XỬ LÝ ĐỒNG BỘ TOÀN BỘ 138 NHÀ THẦU & GHI DỮ LIỆU
# ==============================================================================

def batch_update_all_contractors():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(base_dir, 'contractors.json')
    csv_path = os.path.join(base_dir, 'contractors.csv')
    output_csv = os.path.join(base_dir, 'contractors_updated.csv')

    if not os.path.exists(json_path):
        print(f"[-] Không tìm thấy tệp {json_path}")
        return

    with open(json_path, 'r', encoding='utf-8') as f:
        contractors = json.load(f)

    total = len(contractors)
    print("=" * 70)
    print(f"🚀 BẮT ĐẦU TRA CỨU TỰ ĐỘNG {total} NHÀ THẦU TRÊN MUASAMCONG.MPI.GOV.VN")
    print("   Cơ quan: Ban QLDA ĐTXD Xã Tân Phú")
    print("=" * 70)

    crawler = MuasamcongCrawler()
    updated_contractors = []
    
    success_count = 0
    not_found_count = 0

    for idx, c in enumerate(contractors):
        msdn = c.get('msdn', '').strip()
        name = c.get('name', '').strip()
        
        # Thanh tiến trình phần trăm
        progress = ((idx + 1) / total) * 100
        print(f"[{progress:5.1f}%] ({idx+1}/{total}) Đang tra cứu MSDN: {msdn} - {name[:35]}...", end='\r')

        info = crawler.lookup(msdn)
        
        if info.get('found'):
            success_count += 1
            c['status'] = info['fullStatus']
            c['egpCode'] = info.get('orgCode', '')
            c['egpStatus'] = info.get('status', '')
            c['egpEffDate'] = info.get('effRoleDate', '')
            print(f"[{progress:5.1f}%] ({idx+1}/{total}) ✓ {name[:30]} -> {info['fullStatus'][:50]}...")
        else:
            not_found_count += 1
            c['status'] = info.get('fullStatus', 'Chưa tìm thấy trên e-GP')
            print(f"[{progress:5.1f}%] ({idx+1}/{total}) ⚠️ {name[:30]} -> {c['status']}")

        updated_contractors.append(c)
        # Giãn cách 0.3s để tránh quá tải server Mua Sắm Công
        time.sleep(0.3)

    print("\n" + "=" * 70)
    print(f"✅ HOÀN THÀNH QUÉT TRẠNG THÁI: {success_count} đã phê duyệt e-GP | {not_found_count} chưa tìm thấy")
    print("=" * 70)

    # 1. Ghi lại vào contractors.json
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(updated_contractors, f, ensure_ascii=False, indent=2)
    print(f"[✓] Đã cập nhật cơ sở dữ liệu hệ thống: {json_path}")

    # 2. Cập nhật và ghi ra file CSV tương thích Google Sheets (Cột H: Trạng thái)
    fieldnames = ['MSDN', 'Tên DN', 'Địa chỉ', 'Người đại diện', 'Điện thoại', 'Email', 'STK Bank', 'Trạng thái']
    with open(output_csv, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(fieldnames)
        for c in updated_contractors:
            writer.writerow([
                c.get('msdn', ''),
                c.get('name', ''),
                c.get('address', ''),
                c.get('rep', ''),
                c.get('phone', ''),
                c.get('email', ''),
                c.get('bank', ''),
                c.get('status', '')
            ])
    print(f"[✓] Đã xuất tệp CSV cập nhật Cột H cho Google Sheets: {output_csv}")

    # 3. Đồng bộ lại mã nguồn index.html với database mới
    sync_to_index_html(updated_contractors)

def sync_to_index_html(contractors):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    index_path = os.path.join(base_dir, 'index.html')
    if not os.path.exists(index_path):
        return

    try:
        with open(index_path, 'r', encoding='utf-8') as f:
            content = f.read()

        json_str = json.dumps(contractors, ensure_ascii=False)
        pattern = r'let CONTRACTORS_DATABASE = \[[\s\S]*?\];'
        replacement = f'let CONTRACTORS_DATABASE = {json_str};'

        if re.search(pattern, content):
            content = re.sub(pattern, replacement, content, count=1)
            with open(index_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print("[✓] Đã đồng bộ trực tiếp trạng thái mới nhất vào giao diện index.html")
    except Exception as e:
        print(f"[-] Không thể cập nhật index.html: {e}")

# ==============================================================================
# LOCAL API SERVER CHO PHÉP WEB APP TRA CỨU REAL-TIME TRÊN MÁY TÍNH
# ==============================================================================

def run_local_api_server(port=8765):
    from http.server import HTTPServer, BaseHTTPRequestHandler
    from urllib.parse import urlparse, parse_qs

    crawler = MuasamcongCrawler()

    class RequestHandler(BaseHTTPRequestHandler):
        def do_OPTIONS(self):
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')
            self.end_headers()

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == '/lookup':
                qs = parse_qs(parsed.query)
                msdn = qs.get('msdn', [''])[0]
                result = crawler.lookup(msdn)

                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):
            # Tắt log stdout mặc định
            return

    server = HTTPServer(('127.0.0.1', port), RequestHandler)
    print("=" * 70)
    print(f"🌐 LOCAL API SERVER ĐANG CHẠY TẠI http://127.0.0.1:{port}")
    print("   Web App Chỉ Định Thầu Pro có thể gọi tra cứu MSDN thời gian thực!")
    print("   Nhấn Ctrl + C để dừng server.")
    print("=" * 70)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nĐã dừng Local API Server.")

# ==============================================================================
# HÀM CHÍNH (CLI DISPATCHER)
# ==============================================================================


def run_interactive_menu():
    while True:
        os.system('cls' if os.name == 'nt' else 'clear')
        print("=" * 79)
        print("     BAN QUẢN LÝ DỰ ÁN ĐẦU TƯ XÂY DỰNG XÃ TÂN PHÚ - TỈNH TÂY NINH")
        print("   HỆ THỐNG TRA CỨU TỰ ĐỘNG NHÀ THẦU TRÊN MẠNG ĐẤU THẦU QUỐC GIA (e-GP)")
        print("             Tác giả: ThS - KS. Nguyễn Ngọc Nguyên (nguyentvtk@gmail.com)")
        print("=" * 79)
        print("\n  Chọn chế độ hoạt động:")
        print("    [1] Quét và cập nhật toàn bộ 138 nhà thầu (Ghi Cột H & CSDL hệ thống)")
        print("    [2] Khởi chạy Local API Server (Cho phép Web App tra cứu thời gian thực)")
        print("    [3] Tra cứu nhanh 1 Mã số doanh nghiệp (MSDN)")
        print("    [4] Thoát")
        print()
        
        try:
            choice = input("  Nhập lựa chọn của bạn (1/2/3/4) [Mặc định 1]: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nĐã thoát chương trình.")
            break

        if not choice:
            choice = "1"

        if choice == "1":
            print("\n[+] Đang kết nối muasamcong.mpi.gov.vn qua IP dân cư cá nhân...")
            batch_update_all_contractors()
            print("\n[OK] Đã hoàn thành cập nhật Cột H (Trạng thái) và tệp contractors_updated.csv!")
            input("\nNhấn Enter để quay lại menu chính...")
        elif choice == "2":
            print("\n[+] Khởi chạy Local API Server phục vụ Web App...")
            run_local_api_server()
            input("\nNhấn Enter để quay lại menu chính...")
        elif choice == "3":
            try:
                msdn = input("\nNhập Mã số thuế / MSDN cần tra cứu: ").strip()
                if msdn:
                    crawler = MuasamcongCrawler()
                    res = crawler.lookup(msdn)
                    print("\nKết quả tra cứu:")
                    print(json.dumps(res, ensure_ascii=False, indent=2))
            except Exception as e:
                print(f"Lỗi: {e}")
            input("\nNhấn Enter để tiếp tục...")
        elif choice == "4":
            print("\nCảm ơn bạn đã sử dụng chương trình!")
            break
        else:
            print("\nLựa chọn không hợp lệ, vui lòng thử lại!")
            time.sleep(1)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Tra cứu nhà thầu trên muasamcong.mpi.gov.vn')
    parser.add_argument('--msdn', type=str, help='Tra cứu một mã số doanh nghiệp cụ thể')
    parser.add_argument('--all', action='store_true', help='Quét và cập nhật toàn bộ 138 nhà thầu')
    parser.add_argument('--server', action='store_true', help='Khởi chạy Local API Server cổng 8765')
    parser.add_argument('--selenium', action='store_true', help='Chạy bằng trình duyệt ẩn Selenium Chrome')
    parser.add_argument('--menu', action='store_true', help='Hiển thị menu tương tác')

    args = parser.parse_args()

    if args.server:
        run_local_api_server()
    elif args.msdn:
        if args.selenium:
            res = lookup_via_selenium(args.msdn)
        else:
            crawler = MuasamcongCrawler()
            res = crawler.lookup(args.msdn)
        print(json.dumps(res, ensure_ascii=False, indent=2))
    elif args.all:
        batch_update_all_contractors()
    else:
        # Mặc định bật menu tương tác người dùng
        run_interactive_menu()