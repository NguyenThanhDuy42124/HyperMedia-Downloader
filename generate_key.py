"""
Tool Tạo License Key Cho Admin — HyperMedia Downloader Pro (@NguyenThanhDuy42124)
Hỗ trợ 2 cách tạo key linh hoạt & cực kỳ đơn giản:

1. Tạo Key theo HWID khách gửi:
   python generate_key.py <HWID_CUA_KHACH> [PERM / 1 / 30 / 365 / YYYYMMDD]
   Ví dụ: python generate_key.py 4A21-8F9E-3B12-90CD PERM
   Ví dụ: python generate_key.py 4A21-8F9E-3B12-90CD 30

2. Tạo Key KHÔNG CẦN HWID (nohwid - Tự Bind vĩnh viễn 1 máy khi nhập lần đầu):
   python generate_key.py nohwid [PERM / 1 / 30 / 365 / YYYYMMDD]
   Ví dụ: python generate_key.py nohwid PERM
   Ví dụ: python generate_key.py nohwid 30

3. Chạy trực tiếp Menu tương tác: python generate_key.py
"""
import sys
from datetime import datetime, timedelta, date

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from license_manager import generate_license_key, generate_redeem_key, get_online_date


def parse_exp_type(arg: str) -> str:
    """Chuyển đổi tham số thời hạn thành mã YYYYMMDD hoặc PERM."""
    if not arg or arg.upper() in ["PERM", "TRONDOI", "VINHVIEN", "0", "LIFETIME"]:
        return "PERM"

    if arg.isdigit():
        days = int(arg)
        today = get_online_date()
        exp_d = today + timedelta(days=days)
        return exp_d.strftime("%Y%m%d")

    clean_arg = arg.replace("-", "").replace("/", "")
    if len(clean_arg) == 8 and clean_arg.isdigit():
        return clean_arg

    return "PERM"


def format_exp_desc(exp_code: str) -> str:
    if exp_code == "PERM":
        return "Trọn Đời (Vĩnh Viễn)"
    try:
        dt = datetime.strptime(exp_code, "%Y%m%d").date()
        today = get_online_date()
        days_left = (dt - today).days
        return f"Hạn tới ngày {dt.strftime('%d/%m/%Y')} ({days_left} ngày)"
    except Exception:
        return exp_code


def main():
    print("=" * 65)
    print("TRÌNH TẠO LICENSE KEY — HYPERMEDIA DOWNLOADER PRO (@NguyenThanhDuy42124)")
    print("=" * 65)

    args = sys.argv[1:]

    if len(args) >= 1:
        target = args[0].strip()
        exp_input = args[1].strip() if len(args) >= 2 else "PERM"
        exp_code = parse_exp_type(exp_input)

        if target.lower() == "nohwid":
            key = generate_redeem_key(exp_code)
            print("\nLOẠI KEY: REDEEM KEY (Không cần HWID trước - Tự Bind 1 máy khi nhập lần đầu)")
            print(f"THỜI HẠN: {format_exp_desc(exp_code)}")
            print(f"LICENSE KEY: {key}")
            print("=" * 65)
        else:
            key = generate_license_key(target, exp_code)
            print(f"\nHWID KHACH: {target.upper()}")
            print(f"THỜI HẠN:   {format_exp_desc(exp_code)}")
            print(f"LICENSE KEY: {key}")
            print("=" * 65)
        return

    # Menu tương tác khi không truyền tham số CLI
    print("\nChọn loại Key bạn muốn tạo:")
    print("  [1] Tạo Key Khóa Theo HWID Khách Gửi")
    print("  [2] Tạo Key KHÔNG CẦN HWID (nohwid - Tự Bind vĩnh viễn 1 máy khi nhập lần đầu)")
    choice = input("\nNhập lựa chọn (1 hoặc 2) [Mặc định 1]: ").strip()

    if choice == "2":
        exp_input = input("Nhập thời hạn (Nhập 'PERM' cho trọn đời, hoặc nhập số ngày như '1', '30', '365'): ").strip()
        exp_code = parse_exp_type(exp_input)
        key = generate_redeem_key(exp_code)

        print("\n" + "=" * 50)
        print("LOẠI KEY: REDEEM KEY (Tự khóa vĩnh viễn 1 máy khi nhập lần đầu)")
        print(f"THỜI HẠN: {format_exp_desc(exp_code)}")
        print(f"LICENSE KEY: {key}")
        print("=" * 50)
    else:
        hwid_input = input("Nhập mã HWID của khách: ").strip()
        if not hwid_input:
            print("Mã HWID không được để trống!")
            return

        exp_input = input("Nhập thời hạn (Nhập 'PERM' cho trọn đời, hoặc nhập số ngày như '1', '30', '365'): ").strip()
        exp_code = parse_exp_type(exp_input)
        key = generate_license_key(hwid_input, exp_code)

        print("\n" + "=" * 50)
        print(f"HWID KHACH: {hwid_input.upper()}")
        print(f"THỜI HẠN:   {format_exp_desc(exp_code)}")
        print(f"LICENSE KEY: {key}")
        print("=" * 50)


if __name__ == "__main__":
    main()
