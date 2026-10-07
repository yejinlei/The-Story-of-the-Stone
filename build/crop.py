"""临时工具：把 PDF 中某个位置的字形裁出来拼成一张图，便于肉眼核对。"""
import sys
sys.path.insert(0, 'd:/src/红楼未完/.pylibs')
import pymupdf as fitz
from PIL import Image, ImageDraw

doc = fitz.open('d:/src/红楼未完/红楼梦脂评汇校本.pdf')


def char_boxes(page, want):
    """返回 [(codepoint, rect), ...] 按顺序，want 为需要的码点集合或 None。"""
    rd = page.get_text('rawdict')
    out = []
    for b in rd['blocks']:
        if b['type'] != 0:
            continue
        for l in b['lines']:
            for s in l['spans']:
                for ch in s['chars']:
                    cp = ord(ch['c'])
                    if want is None or cp in want:
                        out.append((cp, fitz.Rect(ch['bbox']), s['font'], round(s['size'], 1)))
    return out


def strip(page, entry, dpi=600, pad=2.0):
    cp, r, font, size = entry
    clip = fitz.Rect(r.x0 - pad, r.y0 - pad, r.x1 + pad, r.y1 + pad)
    pix = page.get_pixmap(dpi=dpi, clip=clip)
    img = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
    return img, f'U+{cp:04X} {font} {size}pt'


def contact_sheet(entries_per_page, out='build/sheet.png', cols=None, cell=260):
    cells = []
    for page, entry in entries_per_page:
        img, label = strip(page, entry)
        img = img.resize((cell, int(cell * img.height / img.width)) if img.width else (cell, cell))
        cells.append((img, label))
    cols = cols or 4
    cw = cell + 8
    ch = max(c[0].height for c in cells) + 34
    rows = (len(cells) + cols - 1) // cols
    sheet = Image.new('RGB', (cols * cw, rows * ch), 'white')
    d = ImageDraw.Draw(sheet)
    for i, (img, label) in enumerate(cells):
        x = (i % cols) * cw + 4
        y = (i // cols) * ch + 24
        sheet.paste(img, (x, y))
        d.text((x, y - 20), label, fill='black')
        d.rectangle([x, y, x + img.width, y + img.height], outline=(200, 0, 0))
    sheet.save(out)
    print('saved', out, sheet.size)
    return out


if __name__ == '__main__':
    legend_page = doc[3]
    order = [0xE04F, 0xE051, 0xE052, 0xE053, 0xE054, 0xE055, 0xE056, 0xE057, 0xE050, 0xE058, 0xE059]
    boxes = char_boxes(legend_page, set(order))
    boxes.sort(key=lambda e: (round(e[1].y0), round(e[1].x0)))
    print([hex(b[0]) for b in boxes])
    contact_sheet([(legend_page, b) for b in boxes], out='build/sheet_legend.png', cols=6, cell=200)
