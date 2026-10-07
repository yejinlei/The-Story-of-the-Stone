"""用系统字体渲染候选汉字，与说明页略字字形比对，交叉验证略字表顺序。"""
import sys
sys.path.insert(0, 'd:/src/红楼未完/.pylibs')
import pymupdf as fitz
from PIL import Image, ImageDraw, ImageFont

N = 40
CAND = ['甲', '己', '庚', '戚', '蒙', '列', '杨', '辰', '眉', '侧', '夹',
        '朱', '墨', '乙', '戌', '卯', '府', '藏', '评', '批', '双', '行']
FONT_PATH = 'C:/Windows/Fonts/msyh.ttc'


def norm(img):
    img = img.resize((N, N), Image.LANCZOS)
    d = [float(v) for v in img.getdata()]
    m = sum(d) / len(d)
    return [v - m for v in d]


def cos(a, b):
    num = sum(x * y for x, y in zip(a, b))
    da = sum(x * x for x in a) ** 0.5
    db = sum(x * x for x in b) ** 0.5
    return num / (da * db + 1e-9)


def render(ch, size=64):
    f = ImageFont.truetype(FONT_PATH, size)
    img = Image.new('L', (size + 8, size + 8), 255)
    d = ImageDraw.Draw(img)
    d.text((4, 2), ch, font=f, fill=0)
    bbox = img.point(lambda v: 255 if v < 128 else 0).getbbox()
    if bbox:
        img = img.crop(bbox)
    return img


def main():
    doc = fitz.open('d:/src/红楼未完/红楼梦脂评汇校本.pdf')
    p = doc[3]
    rd = p.get_text('rawdict')
    glyphs = []
    for b in rd['blocks']:
        if b['type'] != 0:
            continue
        for l in b['lines']:
            for s in l['spans']:
                for ch in s['chars']:
                    cp = ord(ch['c'])
                    if 0xE000 <= cp <= 0xF8FF:
                        glyphs.append((cp, fitz.Rect(ch['bbox'])))
    glyphs.sort(key=lambda e: (round(e[1].y0), round(e[1].x0)))
    refs = {c: norm(render(c)) for c in CAND}
    print('order  codepoint  best  score  2nd 3rd')
    for cp, r in glyphs:
        w, h = r.width, r.height
        inner = fitz.Rect(r.x0 + w * 0.22, r.y0 + h * 0.22, r.x1 - w * 0.22, r.y1 - h * 0.22)
        pix = p.get_pixmap(dpi=800, clip=inner)
        img = Image.frombytes('RGB', (pix.width, pix.height), pix.samples).convert('L')
        v = norm(img)
        sc = sorted(((cos(v, refs[c]), c) for c in CAND), reverse=True)
        print(f'U+{cp:04X}  ' + '  '.join(f'{c}:{s:.2f}' for s, c in sc[:4]))


if __name__ == '__main__':
    main()
