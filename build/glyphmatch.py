"""把正文里出现的私有区字形，与说明页「略字表」的字形做像素比对，确定语义。"""
import sys
sys.path.insert(0, 'd:/src/红楼未完/.pylibs')
import pymupdf as fitz
from PIL import Image

DOC = fitz.open('d:/src/红楼未完/红楼梦脂评汇校本.pdf')
LEGEND_PAGE = 3
LEGEND_ORDER = [0xE04F, 0xE051, 0xE052, 0xE053, 0xE054, 0xE055, 0xE056, 0xE057, 0xE050, 0xE058, 0xE059]
LEGEND_NAME = {
    0xE04F: '甲戌本', 0xE051: '己卯本', 0xE052: '庚辰本', 0xE053: '戚序本', 0xE054: '蒙府本',
    0xE055: '列藏本', 0xE056: '杨藏本', 0xE057: '甲辰本', 0xE050: '眉批', 0xE058: '侧批', 0xE059: '夹批',
}
N = 64


def glyph_img(page, rect, dpi=900):
    pix = page.get_pixmap(dpi=dpi, clip=rect)
    img = Image.frombytes('RGB', (pix.width, pix.height), pix.samples).convert('L')
    bw = img.point(lambda v: 255 if v > 128 else 0).convert('1')
    # 裁掉空白
    bbox = bw.getbbox()
    if bbox:
        bw = bw.crop(bbox)
    return bw.resize((N, N))


def dist(a, b):
    pa, pb = list(a.getdata()), list(b.getdata())
    return sum(1 for x, y in zip(pa, pb) if x != y) / (N * N)


def collect(page_idx, limit=None):
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
    out.sort(key=lambda e: (round(e[1].y0 / 4), e[1].x0))
    return out[:limit] if limit else out


def main():
    lp = DOC[LEGEND_PAGE]
    legend = {}
    for entry in collect(LEGEND_PAGE):
        cp, r = entry
        if cp in LEGEND_NAME:
            legend[cp] = glyph_img(lp, r)

    body_samples = {}
    for pi in range(10, 40):
        for cp, r in collect(pi):
            if cp in body_samples:
                continue
            if r.x0 < 60:  # 页眉噪声
                continue
            body_samples.setdefault(cp, (pi, r))

    print('codepoint  best_match  dist  2nd  样本页')
    for cp, (pi, r) in sorted(body_samples.items()):
        g = glyph_img(DOC[pi], r)
        scores = sorted(((dist(g, lg), lcp) for lcp, lg in legend.items()))
        best = scores[:2]
        print(f'U+{cp:04X}  {LEGEND_NAME.get(best[0][1])}  {best[0][0]:.3f}  '
              f'{LEGEND_NAME.get(best[1][1])} {best[1][0]:.3f}  p{pi}')


if __name__ == '__main__':
    main()
