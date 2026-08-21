"""
座標変換ユーティリティ

source of truth: mm (ミリメートル)

層構成:
- Layer 1: ブラウザ DOM (px) ← UI操作
- Layer 2: Canonical (mm) ← Database保存
- Layer 3: PDF Render (pt) ← PDFRenderService
"""

from decimal import Decimal


# ===== 定数 =====

# A4 サイズ（デフォルトテンプレート）
A4_WIDTH_MM = 210.0
A4_HEIGHT_MM = 297.0

# ブラウザ表示サイズ（CSS で固定、テンプレート幅に応じてスケーリング）
BROWSER_PDF_WIDTH_PX = 600
BROWSER_PDF_HEIGHT_PX = 848

# PDF pt 変換（1 inch = 72 points, 1 inch = 25.4 mm）
POINTS_PER_MM = 72 / 25.4  # ≈ 2.834645669
MM_PER_POINT = 25.4 / 72   # ≈ 0.3528


# ===== Coordinate Converter =====

class CoordinateConverter:
    """座標系変換エンジン"""

    @staticmethod
    def get_scale_factors(template_width_mm=None, template_height_mm=None):
        """
        テンプレートサイズに応じた scale factor を返す

        Args:
            template_width_mm: テンプレート幅（デフォルト A4）
            template_height_mm: テンプレート高さ（デフォルト A4）

        Returns:
            (px_per_mm_x, px_per_mm_y): px/mm の比率
        """
        w = template_width_mm or A4_WIDTH_MM
        h = template_height_mm or A4_HEIGHT_MM

        px_per_mm_x = BROWSER_PDF_WIDTH_PX / w
        px_per_mm_y = BROWSER_PDF_HEIGHT_PX / h

        return px_per_mm_x, px_per_mm_y

    @staticmethod
    def mm_to_px(mm_value, axis='x', template_width_mm=None, template_height_mm=None):
        """
        mm → px 変換

        Args:
            mm_value: ミリメートル値
            axis: 'x' または 'y'
            template_width_mm: テンプレート幅（オプション）
            template_height_mm: テンプレート高さ（オプション）

        Returns:
            float: ピクセル値
        """
        px_per_mm_x, px_per_mm_y = CoordinateConverter.get_scale_factors(
            template_width_mm, template_height_mm
        )

        if axis == 'x':
            return float(mm_value) * px_per_mm_x
        else:  # 'y'
            return float(mm_value) * px_per_mm_y

    @staticmethod
    def px_to_mm(px_value, axis='x', template_width_mm=None, template_height_mm=None):
        """
        px → mm 変換

        Args:
            px_value: ピクセル値
            axis: 'x' または 'y'
            template_width_mm: テンプレート幅（オプション）
            template_height_mm: テンプレート高さ（オプション）

        Returns:
            float: ミリメートル値
        """
        px_per_mm_x, px_per_mm_y = CoordinateConverter.get_scale_factors(
            template_width_mm, template_height_mm
        )

        if axis == 'x':
            return float(px_value) / px_per_mm_x
        else:  # 'y'
            return float(px_value) / px_per_mm_y

    @staticmethod
    def mm_to_pt(mm_value):
        """
        mm → pt 変換（PDF render用）

        Args:
            mm_value: ミリメートル値

        Returns:
            float: ポイント値
        """
        return float(mm_value) * POINTS_PER_MM

    @staticmethod
    def pt_to_mm(pt_value):
        """
        pt → mm 変換

        Args:
            pt_value: ポイント値

        Returns:
            float: ミリメートル値
        """
        return float(pt_value) * MM_PER_POINT

    @staticmethod
    def round_mm(value, decimals=2):
        """
        mm 値を丸める（保存時用）

        Args:
            value: 数値
            decimals: 小数点以下の桁数

        Returns:
            float: 丸められた値
        """
        return round(float(value), decimals)


# ===== テスト用 =====

if __name__ == '__main__':
    converter = CoordinateConverter()

    # Test 1: mm → px
    print("Test 1: mm → px")
    x_mm = 105.0
    x_px = converter.mm_to_px(x_mm, 'x')
    print(f"  {x_mm}mm → {x_px:.2f}px (expected ≈ 300px)")

    # Test 2: px → mm
    print("\nTest 2: px → mm")
    x_px = 300
    x_mm = converter.px_to_mm(x_px, 'x')
    print(f"  {x_px}px → {x_mm:.2f}mm (expected ≈ 105mm)")

    # Test 3: mm → pt
    print("\nTest 3: mm → pt")
    x_mm = 10.0
    x_pt = converter.mm_to_pt(x_mm)
    print(f"  {x_mm}mm → {x_pt:.2f}pt (expected ≈ 28.35pt)")

    # Test 4: pt → mm
    print("\nTest 4: pt → mm")
    x_pt = 28.35
    x_mm = converter.pt_to_mm(x_pt)
    print(f"  {x_pt}pt → {x_mm:.2f}mm (expected ≈ 10mm)")

    # Test 5: Round mm
    print("\nTest 5: Round mm")
    value = 15.123456
    rounded = converter.round_mm(value, 2)
    print(f"  {value} → {rounded} (expected 15.12)")
