"""字形像素比对 v2：多样本、全矩阵。"""
import sys
sys.path.insert(0, 'd:/src/红楼未完/.pylibs')
import pymupdf as fitz
from PIL import Image

DOC = fitz.open('d:/src/红楼未完/红楼梦脂评汇校本.pdf')
LEGEND_PAGE = 3
LEGEND_NAME = {
    0xE04F: '甲戌', 0xE051: '己卯', 0xE052: '庚辰', 0xE053: '戚序', 0xE054: '蒙府',
    0xE055: '列藏', 0xE056: '杨藏', 0xE057: '甲辰', 0xE050: '眉批', 0xE058: '侧批', 0xE059: '夹批',
}
N = 48


def glyph_img(page, rect, dpi=1000):
    pad = max(rect.width, rect.height) * 0.06
    clip = fitz.Rect(rect.x0 - pad, rect.y0 - pad, rect.x1 + pad, rect.y1 + pad)
    pix = page.get_pixmap(dpi=dpi, clip=clip)
    img = Image.frombytes('RGB', (pix.width, pix.height), pix.samples).convert('L')
    return img.resize((N, N), Image.LANCZOS)


def dist(a, b):
    ra, rb = [float(v) for v in a.getdata()], [float(v) for v in b.getdata()]
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    va = [v - ma for v in ra]
    vb = [v - mb for v in rb]
    num = sum(x * y for x, y in zip(va, vb))
    da = sum(x * x for x in va) ** 0.5
    db = sum(x * x for x in vb) ** 0.5
    return 1 - num / (da * db + 1e-9)


def collect(page_idx):
    page = DOC[page_idx]
    rd = page.get_text('rawdict')
    out = []
    for b in rd['blocks']:
        if b['type'] != 0:
            continue
        for l in b['lines']:
            for s in l['spans']:
                for ch in s['chars']:
                    cp = ord(ch['c'])
                    if 0xE000 <= cp <= 0xF8FF:
                        out.append((cp, fitz.Rect(ch['bbox'])))
    return out


def main():
    lp = DOC[LEGEND_PAGE]
    legend = {cp: glyph_img(lp, r) for cp, r in collect(LEGEND_PAGE) if cp in LEGEND_NAME}
    samples = {}
    for pi in range(10, 60):
        for cp, r in collect(pi):
            if r.x0 < 70:
                continue
            samples.setdefault(cp, []).append((pi, r))
    names = list(LEGEND_NAME.values())
    print('body\\legend'.ljust(10) + ''.join(n.ljust(8) for n in names))
    for cp, lst in sorted(samples.items()):
        row = []
        for lcp in LEGEND_NAME:
            best = min(dist(glyph_img(DOC[pi], r), legend[lcp]) for pi, r in lst[:4])
            row.append(best)
        order = sorted(range(len(row)), key=lambda i: row[i])
        print(f'U+{cp:04X}  ' + ''.join(f'{v:.3f}  ' for v in row)
              + f'  => {names[order[0]]} / {names[order[1]]}   n={min(len(lst),4)}')


if __name__ == '__main__':
    main()
