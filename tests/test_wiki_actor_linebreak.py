"""维基演员简介的行结构：`<br>` 分行、段落分隔、写库前的 `<br/>` 整形。

用户反馈「刮削的演员信息没有按 wiki 网页那个换行」，涉及两处：

1. 维基正文常在一个段落内用 `<br>` 分行（作品列表、逐条履历），旧解析只拼接
   `.//text()`，这些行会被并成一整行——网页上分行、刮下来没有换行；
2. 裸 `\\n` 在服务器端按 HTML 渲染时会被折叠成空格，写库前必须统一转成 `<br/>`，
   否则「个人资料」段的生日 / 别名等行同样挤成一行。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mdcx.config.enums import EmbyAction
from mdcx.models.emby import EMbyActressInfo, to_emby_overview
from mdcx.tools.wiki_actor import WikiActorProfile, _parse_wiki_page, apply_wiki_profile

_HTML = """
<html><body><div class="mw-parser-output">
<p>2021年8月、アイデアポケットの専属女優としてAVデビュー<sup>[1]</sup>。所属事務所はX。</p>
<p>2021年12月から2022年1月までアタッカーズ専属となり、2月より再び企画単体女優となる。</p>
<p>日本のロマンポルノに憧れて! 昭和を愛するAVデビュー<br />
出し（9月28日、本中）<br/>女交際 中出しOK18歳<br /></p>
<ul><li>2021年10月1日 - 作品A</li><li>2021年11月2日 - 作品B</li></ul>
</div></body></html>
"""


def _page_overview() -> str:
    page = _parse_wiki_page("https://ja.wikipedia.org/wiki/test", "ja", _HTML)
    assert page.overview is not None
    return page.overview


def test_br_inside_paragraph_kept_as_newline():
    """段落内的 `<br>` 断行不能丢：三行作品信息应各占一行。"""
    overview = _page_overview()
    assert "AVデビュー\n出し（9月28日、本中）\n女交際 中出しOK18歳" in overview
    assert "AVデビュー出し（9月28日" not in overview


def test_list_items_and_paragraphs_stay_separate():
    """列表项一行一条，段落之间用空行分隔（与网页排版一致）。"""
    overview = _page_overview()
    assert "作品A\n" in overview
    assert "作品A2021年11月2日" not in overview
    assert "所属事務所はX。\n\n2021年12月から" in overview


def test_apply_wiki_profile_keeps_profile_block_lines():
    """简介版式：「个人资料」→「外部链接」→ 正文；日文模式下段标题取日文。

    用户 2026-11-08 给出的目标观感（湊莉久词条）：
    `===== 個人情報 =====` 一行一条 → `===== 外部リンク =====` 一行一条 → 正文段落。
    """
    profile = WikiActorProfile(
        language="ja",
        infobox=["別名: 上村陽菜（うえむらはるな）", "生年月日: 1993年8月1日"],
        provider_ids={"imdb": "nm7706859", "twitter": "riku_minato", "xhamster": "riku-minato"},
        source_url="https://ja.wikipedia.org/wiki/湊莉久",
        overview="段落一\n\n段落二",
    )
    info = EMbyActressInfo(name="湊莉久", server_id="s", id="i")
    apply_wiki_profile(info, profile, emby_on=[EmbyAction.ACTOR_INFO_JA])

    assert info.overview == (
        "===== 個人情報 =====\n"
        "別名: 上村陽菜（うえむらはるな）\n"
        "生年月日: 1993年8月1日\n"
        "\n"
        "===== 外部リンク =====\n"
        "IMDb: https://www.imdb.com/name/nm7706859\n"
        "Twitter: https://twitter.com/riku_minato\n"
        "xHamster: https://xhamster.com/pornstars/riku-minato\n"
        "Wikipedia: https://ja.wikipedia.org/wiki/湊莉久\n"
        "\n"
        "段落一\n\n段落二"
    )


def test_apply_wiki_profile_chinese_headings_without_links():
    """简中模式段标题用中文；没有任何外链时整段不写，不留空标题。"""
    profile = WikiActorProfile(language="zh", birthday="1993-08-01", birthplace="神奈川県")
    info = EMbyActressInfo(name="湊莉久", server_id="s", id="i")
    apply_wiki_profile(info, profile, emby_on=[EmbyAction.ACTOR_INFO_ZH_CN])

    assert info.overview == "===== 个人资料 =====\n生日: 1993-08-01\n出生地: 神奈川県"


def test_to_emby_overview_turns_newlines_into_br():
    """写库整形：裸换行（含 CRLF）转 `<br/>`，已有 `<br>` 变体原样保留。"""
    assert to_emby_overview("a\nb\r\nc") == "a<br/>b<br/>c"
    assert to_emby_overview("a<br>b<br/>c") == "a<br>b<br/>c"
    assert to_emby_overview("") == ""
    assert to_emby_overview(None) == ""


def test_to_emby_overview_drops_placeholder():
    """占位文案仍先清洗再整形：清空后不留下多余 `<br/>`。"""
    assert to_emby_overview("无维基百科信息, 从 minnano-av 数据库补全女优信息") == ""
    assert to_emby_overview("正文\n无维基百科信息, 从 minnano-av 数据库补全女优信息\n尾段") == ("正文<br/><br/>尾段")


# --- 旧 wiki.py 路径（search_wiki / parse_detail，保留的老实现）同样要按 <br> 断行 ---

_MOBILE_HTML = """
<html><body><div class="mw-parser-output"><div id="mf-section-0">
<p>第一段。</p>
<p>行一<br />行二<br/>行三</p>
</div></div></body></html>
"""


def test_legacy_wiki_introduction_keeps_br():
    """旧实现的导语提取同样不能把段落内的 `<br>` 行并成一行。"""
    import bs4

    from mdcx.tools.wiki import _extract_introduction

    soup = bs4.BeautifulSoup(_MOBILE_HTML, "lxml")
    actor_output = soup.find(class_="mw-parser-output")
    text = _extract_introduction(actor_output)
    assert "行一\n行二\n行三" in text
    assert "行一 行二" not in text


def test_infobox_skips_imperial_unit_rows():
    """信息框的「表示英米単位系」折叠块与展开后的英制同名行不进简介（实测湊莉久词条）。"""
    html = """<div class="mw-parser-output"><table class="infobox"><tbody>
      <tr><th>身長 / 体重</th><td>160 cm / ― kg</td></tr>
      <tr><th>表示英米単位系</th><td>表示英米単位系身長 / 体重 5 ft 3 in / ― lb</td></tr>
      <tr><th>身長 / 体重</th><td>5 ft 3 in / ― lb</td></tr>
      <tr><th>スリーサイズ</th><td>82 - 58 - 83 cm</td></tr>
      <tr><th>スリーサイズ</th><td>32 - 23 - 33 in</td></tr>
    </tbody></table></div>"""
    page = _parse_wiki_page("https://ja.wikipedia.org/wiki/test", "ja", html)
    assert page.infobox == ("身長 / 体重: 160 cm / ― kg", "スリーサイズ: 82 - 58 - 83 cm")


def test_infobox_br_becomes_ideographic_comma():
    """信息框单元格里的 `<br>` 分隔的多值，合成一行并用「、」连接（別名 / 専属契約）。"""
    html = """<div class="mw-parser-output"><table class="infobox"><tbody>
      <tr><th>別名</th><td>上村陽菜（うえむらはるな）<br />CHIAKI／Chiaki（ちあき）<br />三浦莉嘉（みうらりか）</td></tr>
      <tr><th>専属契約</th><td>S1 NO.1 STYLE<br />（2014年7月 - 2020年3月）<br />FALENO</td></tr>
    </tbody></table></div>"""
    page = _parse_wiki_page("https://ja.wikipedia.org/wiki/test", "ja", html)
    assert page.infobox == (
        "別名: 上村陽菜（うえむらはるな）、CHIAKI／Chiaki（ちあき）、三浦莉嘉（みうらりか）",
        "専属契約: S1 NO.1 STYLE（2014年7月 - 2020年3月）、FALENO",
    )


def test_infobox_keeps_all_rows_and_dedupes_labels():
    """个人资料段全拿：只按标签去重（同名字段保留第一次出现），不额外过滤字段。"""
    html = """<div class="mw-parser-output"><table class="infobox"><tbody>
      <tr><th>生年月日</th><td>1994年7月10日</td></tr>
      <tr><th>ジャンル</th><td>アダルトビデオ</td></tr>
      <tr><th>チャンネル</th><td>つかちゃんねる</td></tr>
      <tr><th>ジャンル</th><td>エンターテインメント</td></tr>
      <tr><th>登録者数</th><td>8.79万人</td></tr>
      <tr><th>総再生回数</th><td>851.5万回</td></tr>
    </tbody></table></div>"""
    page = _parse_wiki_page("https://ja.wikipedia.org/wiki/test", "ja", html)
    assert page.infobox == (
        "生年月日: 1994年7月10日",
        "ジャンル: アダルトビデオ",
        "チャンネル: つかちゃんねる",
        "登録者数: 8.79万人",
        "総再生回数: 851.5万回",
    )


def test_overview_puts_person_section_before_history():
    """正文顺序：导语 → 人物 → 经历（维基原文里経歴在人物前面的也要调过来）。"""
    html = """<div class="mw-parser-output">
      <p>导语段落。</p>
      <h2>経歴</h2><p>经历段落。</p>
      <h2>人物</h2><p>人物段落。</p>
    </div>"""
    page = _parse_wiki_page("https://ja.wikipedia.org/wiki/test", "ja", html)
    assert page.overview == "导语段落。\n\n人物段落。\n\n经历段落。"


def test_profile_lines_appends_entry_name_when_searched_by_alias():
    """搜别名命中（妃月るい → 词条名 音琴るい）时，別名行末尾补上现名；已存在不重复。"""
    profile = WikiActorProfile(
        language="ja",
        name="音琴るい",
        searched_name="妃月るい",
        infobox=["別名: 音琴 留衣（中華圏）、妃月るい、ぺち"],
    )
    info = EMbyActressInfo(name="妃月るい", server_id="s", id="i")
    apply_wiki_profile(info, profile, emby_on=[EmbyAction.ACTOR_INFO_JA])
    # 搜索名（妃月るい）本身不再列进別名，只补现名
    assert info.overview == "===== 個人情報 =====\n別名: 音琴 留衣（中華圏）、ぺち、音琴るい"


def test_profile_lines_unchanged_when_searched_by_entry_name():
    """搜的就是词条名（音琴るい）时不额外补，避免把现名重复写进別名。"""
    profile = WikiActorProfile(
        language="ja",
        name="音琴るい",
        searched_name="音琴るい",
        infobox=["別名: 音琴 留衣（中華圏）、妃月るい、ぺち"],
    )
    info = EMbyActressInfo(name="音琴るい", server_id="s", id="i")
    apply_wiki_profile(info, profile, emby_on=[EmbyAction.ACTOR_INFO_JA])
    assert info.overview == "===== 個人情報 =====\n別名: 音琴 留衣（中華圏）、妃月るい、ぺち"


def test_profile_lines_drops_searched_name_from_alias():
    """搜的名字不出现在「別名」行：搜「ぺち」时ぺち被去掉，现名仍补上。"""
    profile = WikiActorProfile(
        language="ja",
        name="音琴るい",
        searched_name="ぺち",
        infobox=["別名: 音琴 留衣（中華圏）、妃月るい、ぺち"],
    )
    info = EMbyActressInfo(name="ぺち", server_id="s", id="i")
    apply_wiki_profile(info, profile, emby_on=[EmbyAction.ACTOR_INFO_JA])
    assert info.overview == "===== 個人情報 =====\n別名: 音琴 留衣（中華圏）、妃月るい、音琴るい"
