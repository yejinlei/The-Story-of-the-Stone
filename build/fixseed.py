import pathlib

p = pathlib.Path('honglou/poems.py')
s = p.read_text(encoding='utf-8')
fix = [
 ("('留余', '红楼梦十二支曲·留余庆', '曲', None, '（警幻新制）', 5)",
  "('留馀庆', '红楼梦十二支曲·留余庆', '曲', None, '（警幻新制）', 5)"),
]
drop = [
 "    ('南面而坐', '灯谜·镜子', '四言谜', 4, '贾宝玉', 22),\n",
 "    ('騄駬何劳缚紫绳', '灯谜·走马灯（黛玉）', '七绝', 4, '林黛玉', 22),\n",
 "    ('落尽残红绿正肥', '柳絮词·蝶恋花', '词', None, '贾宝玉', 70),\n",
 "    ('一夜北风紧', '芦雪庵即景联句', '联句', None, '王熙凤等', 50),\n",
]
for a, b in fix:
    s = s.replace(a, b)
for d in drop:
    if d in s:
        s = s.replace(d, '')
p.write_text(s, encoding='utf-8')
print('ok')
