DEFAULT_POSITIONS = {
    'title': {'label': 'タイトル', 'x': 120, 'y': 60, 'w': 340, 'h': 300, 'font_size': 28, 'writing_mode': 'vertical'},
    'lead_copy': {'label': 'リードコピー', 'x': 120, 'y': 110, 'w': 340, 'h': 120, 'font_size': 16, 'writing_mode': 'horizontal'},
    'summary': {'label': '概要', 'x': 120, 'y': 150, 'w': 340, 'h': 260, 'font_size': 12, 'writing_mode': 'vertical'},
    'store_name': {'label': '店舗名', 'x': 120, 'y': 400, 'w': 260, 'h': 60, 'font_size': 12, 'writing_mode': 'horizontal'},
    'address': {'label': '住所', 'x': 120, 'y': 440, 'w': 260, 'h': 80, 'font_size': 12, 'writing_mode': 'horizontal'},
    'contact': {'label': 'TEL・連絡先', 'x': 120, 'y': 500, 'w': 260, 'h': 60, 'font_size': 12, 'writing_mode': 'horizontal'},
    'closed_days': {'label': '定休日', 'x': 120, 'y': 540, 'w': 260, 'h': 60, 'font_size': 12, 'writing_mode': 'horizontal'},
    'parking': {'label': '駐車場', 'x': 120, 'y': 580, 'w': 260, 'h': 60, 'font_size': 12, 'writing_mode': 'horizontal'},
    'main_image': {'label': 'メイン画像', 'x': 400, 'y': 100, 'w': 300, 'h': 200},
    'sub_image1': {'label': 'サブ画像1', 'x': 400, 'y': 350, 'w': 140, 'h': 140},
    'sub_image2': {'label': 'サブ画像2', 'x': 560, 'y': 350, 'w': 140, 'h': 140},
}

DEFAULT_FIELD_LABELS = {
    key: value.get('label', key)
    for key, value in DEFAULT_POSITIONS.items()
}
