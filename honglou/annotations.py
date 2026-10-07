"""脂评批语的「略字」解码表。

《红楼梦脂评汇校本》用私用区（PUA）字符标记批语来源版本与批注类型。
PDF 里存在两套同名的 EUDC 字体：第一套承载「版本略字」，第二套承载
「类型略字」，两者码点重叠，必须按在一个标记串中的位置区分：

    标记串 = [版本略字][类型略字]

版本略字（第 1 位）
    U+E04F 甲戌本   U+E051 己卯本   U+E052 庚辰本   U+E053 戚序(有正)本
    U+E054 蒙府本   U+E055 列藏本   U+E056 杨藏本   U+E057 甲辰本

类型略字（第 2 位）
    U+E04F 眉批（原抄在页眉）  U+E053 夹批（双行小字）  U+E054 侧批（正文右侧）

映射由「说明页」略字表的字形位置 + 字形像素比对双重确认。
"""
from __future__ import annotations

EDITION_MARK = {
    "\ue04f": "甲戌", "\ue051": "己卯", "\ue052": "庚辰", "\ue053": "戚序",
    "\ue054": "蒙府", "\ue055": "列藏", "\ue056": "杨藏", "\ue057": "甲辰",
}

TYPE_MARK = {
    "\ue04f": "眉批", "\ue053": "夹批", "\ue054": "侧批",
}

# 版本全称 / 存回情况 / 批语概况
EDITIONS = {
    "甲戌": dict(
        full="甲戌本（脂砚斋重评石头记）", short="甲戌",
        extant="存十六回：一至八、十三至十六、二十五至二十八",
        note="文字最优，批语最富，多朱笔眉批、侧批，独有其重要批语。",
    ),
    "己卯": dict(
        full="己卯本（脂砚斋重评石头记）", short="己卯",
        extant="存一至二十、三十一至四十、五十五至五十八、六十一至七十回",
        note="避「祥」「晓」讳，与庚辰本同源，多双行夹批。",
    ),
    "庚辰": dict(
        full="庚辰本（脂砚斋重评石头记）", short="庚辰",
        extant="存七十八回，缺第六十四、六十七回",
        note="最完整的脂本，抄手草率；批语含眉批、夹批、回前回后批。",
    ),
    "戚序": dict(
        full="戚序本（有正书局石印本）", short="戚序",
        extant="八十回全",
        note="经整理，有回前回后「总评」，夹批经删并改写。",
    ),
    "蒙府": dict(
        full="蒙古王府本", short="蒙府",
        extant="前八十回为脂本，后四十回配以程甲本",
        note="批语极多，多为双行夹批，间有侧批，部分为他本所无。",
    ),
    "列藏": dict(
        full="列藏本（苏联科学院东方学研究所藏）", short="列藏",
        extant="存七十八回，缺第五、六回",
        note="第六十四、六十七回文字独特，是汇校本此二回的底本。",
    ),
    "杨藏": dict(
        full="杨藏本（梦稿本）", short="杨藏",
        extant="一百二十回",
        note="兼有脂本与程高改文，为研究改文的重要材料。",
    ),
    "甲辰": dict(
        full="甲辰本（梦觉主人序本）", short="甲辰",
        extant="八十回全",
        note="脂本向程高本过渡的桥梁，批语多经删削。",
    ),
}

# 颜色（PDF 中的 RGB 整数）→ 墨色
INK_BY_COLOR = {
    16711680: "朱批",   # 红：甲、庚本朱批
    17451: "墨批",      # 墨绿：甲、己、庚本墨批
    139: "墨批",        # 深蓝：其余各本墨批
    0: "墨批",
}

PUA_RANGE = ("\ue000", "\uf8ff")


def is_mark(ch: str) -> bool:
    return "\ue000" <= ch <= "\uf8ff"


def decode_marker(run: str) -> tuple[list[str], str]:
    """把标记串解码为 (版本列表, 批注类型)。"""
    editions = []
    atype = ""
    for i, ch in enumerate(run):
        if i == 0:
            editions.append(EDITION_MARK.get(ch, "未详本"))
        elif i == 1:
            atype = TYPE_MARK.get(ch, "")
        else:
            editions.append(EDITION_MARK.get(ch, "未详本"))
    return editions, atype
