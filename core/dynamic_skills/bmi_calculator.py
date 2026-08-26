def bmi_calculator(args):
    """Tinh BMI. Tham so: 'kg m'"""
    try:
        w, h = map(float, args.split())
        bmi = w / (h * h)
        return f"BMI của bạn là {bmi:.2f}"
    except:
        return "Vui lòng nhập định dạng: 'cân_nặng chiều_cao' (VD: 70 1.75)"

DESCRIPTION = "Tính chỉ số BMI từ cân nặng và chiều cao."
USAGE = "ACTION: bmi_calculator | <cân_nặng> <chiều_cao>"