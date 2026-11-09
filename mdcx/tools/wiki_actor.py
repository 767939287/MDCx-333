"""Wikidata 检索 + 维基百科演员档案解析（移植自 sqzw-x/amane）。

与原 ``mdcx/tools/wiki.py`` 的差异：

- 一次调用完成「Wikidata 检索 → 实体校验 → 按语言取词条 → 解析简介/信息框」，
  不再依赖「先拿 URL 再请求详情」的两次手递手；
- 词条语言由 ``config.actor_wiki_languages`` 决定（zh / ja / en，按顺序回退），
  检索语言固定 ja → zh → en；
- 请求统一带可识别 User-Agent，并复用 ``web_async`` 的 MediaWiki 限速器
  （未识别 UA 10 req/min、可识别 UA 200 req/min，这里按更保守的 2 req/s + 180 req/min）；
- 只取正文与信息框，不识别「年齢認証」等词做拦截判定（正文用 ``get_text``）。

解析结果先落到 :class:`WikiActorProfile`，再由 :func:`apply_wiki_profile`
写进 ``EMbyActressInfo``。这样解析与 Emby 字段映射分离，解析部分可以离线单测。
"""

from __future__ import annotations

import calendar
import math
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, NamedTuple
from urllib.parse import quote

import zhconv
from parsel import Selector

from ..config.manager import manager
from ..config.resources import resources
from ..models.emby import EMbyActressInfo
from .wiki import _wiki_headers

if TYPE_CHECKING:
    from ..config.enums import EmbyAction

# 拉丁短语子串大小写不敏感。日语「女優」= 普通女演员，单独匹配会带入非 AV 条目。
_AV_KEYWORDS: tuple[str, ...] = (
    "av idol",
    "av actress",
    "av actor",
    "adult actress",
    "adult actor",
    "adult model",
    "porn actress",
    "porn actor",
    "pornographic",
    "japanese idol",
    "gravure",
    "av女優",
    "av女优",
    "av男優",
    "av男优",
    "avアイドル",
    "av監督",
    "アダルト",
    "成人映画",
    "成人影片",
)

# 英文描述里行业词与角色词分离出现时仍算命中（如 "Japanese adult video actress"）。
_AV_INDUSTRY_RE = re.compile(r"\b(?:av|adult|porn|xxx)\b", re.IGNORECASE)
_AV_ROLE_RE = re.compile(r"\b(?:actress|actor|idol|model|star)\b", re.IGNORECASE)

# 检索语言固定；词条语言另由配置决定。
_SEARCH_LANGUAGES: tuple[str, ...] = ("ja", "zh", "en")
_SEARCH_CANDIDATE_LIMIT = 5

# 词条语言默认优先级；config.actor_wiki_languages 的取值集合从这里收窄。
WIKI_LANGUAGES: tuple[str, ...] = ("zh", "ja", "en")

# 词条 URL 的变体路径段：中文维基的 wiki/ 不转换原文，取简体正文必须改用变体路径。
_WIKI_VARIANTS: dict[str, str] = {"zh": "zh-cn"}

_PARSER_OUTPUT_CLASS = "mw-parser-output"
_PARSER_OUTPUT = f".{_PARSER_OUTPUT_CLASS}"
_CONTENT_NODES = ".//h1|.//h2|.//h3|.//h4|.//h5|.//h6|.//p|.//ul|.//ol"
_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
# 列表整块取用（每个 li 一行），嵌套列表与列表内的 p 都不再单独取，避免重复。
_LIST_TAGS = frozenset({"ul", "ol"})
_SKIP_WRAPPERS = frozenset({"table", "figure"})

# 章节白名单：命中即整节取用，未命中的章节（作品 / 出演 / 脚注等）只保留导语。
# 标题写法在词条之间不统一，漏收的写法会让该节整节丢弃，新出现的写法要补进白名单。
# 关键字只存简体形态；比对前折叠标题：中文繁体经 zhconv 转换，日文词条不做变体转换。
_JA_HEADING_FOLD = str.maketrans({"経": "经"})
_SECTION_KEYWORDS: tuple[str, ...] = (
    "人物",
    "小传",
    "简历",
    "简介",
    "经历",
    "履历",
    "略历",
    "来历",
    "生平",
    "生涯",
    "背景",
    "私生活",
    "个人生活",
    "プロフィール",
    "生い立ち",
    "early life",
    "career",
    "biography",
    "personal life",
    "background",
)

# 引用标记 [1] / [ 3 ] / [注 1] / [要出典]；全角括号与内部空白一并容忍。
_CITATION_RE = re.compile(r"[\[［]\s*(?:\d+|注\s*\d*|注釈\s*\d*|要出典|要ページ番号)\s*[\]］]")
# 标题里的 [編集] / [edit] 是维基皮肤注入的编辑入口，不属于标题文本。
_EDIT_LINK_RE = re.compile(r"[\[［]\s*(?:編集|編輯|edit)\s*[\]］]", re.IGNORECASE)

# 存档标注：链接后的「页面存档备份，存于互联网档案馆」一类模板后缀，是导航不是正文，一律删除。
# 次序即优先级：长的整句排在短的残句前面，「页面存档备份」必须排在「存档于」之前才能匹配到句末。
_ARCHIVE_CLAUSES: tuple[str, ...] = (
    r"原始(?:内容|內容)(?:存档|存檔|归档|歸檔)(?:于|於)?\s*[\d年月日./\-－—]*",
    r"(?:页面|頁面|网页|網頁)(?:存档|存檔)(?:备份|備份)\s*[，,、]?\s*"
    r"存(?:于|於)(?:互联网档案馆|互聯網檔案館|網際網路檔案館)",
    r"\d{4}年\d{1,2}月\d{1,2}日(?:時点|現在)?の?(?:オリジナル|オ[リり]ジナル)(?:より)?アーカイブ",
    r"ウェイバックマシン(?:\s*[（(][^）)]{0,24}[）)])?",
    r"(?:页面|頁面|网页|網頁)(?:存档|存檔)(?:备份|備份)",
    r"(?:存档|存檔|归档|歸檔)(?:于|於)?\s*[\d年月日./\-－—]+",
    r"存(?:于|於)(?:互联网档案馆|互聯網檔案館|網際網路檔案館)",
    r"archived?\s+(?:from|at)\s+the\s+original(?:\s+on)?(?:[\s,]+[\w]{1,9}){0,4}[\s,]+\d[\d\-/.,]*",
    r"(?:original\s+)?archived?\s+on(?:[\s,]+[\w]{1,9}){0,4}[\s,]+\d[\d\-/.,]*",
    r"archived?\s+from\s+the\s+original",
)
_ARCHIVE_CLAUSES_RE = "|".join(_ARCHIVE_CLAUSES)
# 整段被括号包裹的标注连同括号一起删；没有括号的残句删到句读为止。
_ARCHIVE_BRACKET_RE = re.compile(r"\s*[（(〔]\s*(?:" + _ARCHIVE_CLAUSES_RE + r")\s*[）)〕]", re.IGNORECASE)
_ARCHIVE_TAIL_RE = re.compile(r"(?:" + _ARCHIVE_CLAUSES_RE + r")[。．.]?", re.IGNORECASE)
# 「2020年1月15日閲覧」是引用模板注入的访问日期，同样不属于正文。
_ACCESS_DATE_RE = re.compile(r"[（(〔]\s*[\d年月日./\-－—\s]{2,24}(?:閲覧|閱覽|阅读|閱讀)\s*[）)〕]")
# 上标序号与「↑」是参考文献列表的定位标记，只可能来自被错误收录的列表。
_REF_MARKER_RE = re.compile(r"[\ue000-\uf8ff↑]")
# 删空括号后留下的空括号本身也要删除；并排的句读合并为一个，竖排省略号是正常写法，不合并。
_EMPTY_BRACKET_RE = re.compile(r"\s*[（(〔]\s*[）)〕]")
_TIDY_PUNCT_RE = re.compile(r"([。．.！!？?])\1+|[、,，]\s*(?=[。．.、,，；;：:]|$)|[。．.、,，](?=[。．.、,，；;：:])")

# 章节分类：正文段落排成「导语 → 人物类 → 经历类 → 其它白名单章节」。
# 关键字存简体形态；比对前先做与 _is_section 相同的折叠。
_PERSON_SECTIONS: tuple[str, ...] = (
    "人物",
    "小传",
    "简介",
    "私生活",
    "个人生活",
    "背景",
    "生い立ち",
    "プロフィール",
    "early life",
    "personal life",
    "background",
)
_HISTORY_SECTIONS: tuple[str, ...] = (
    "简历",
    "经历",
    "履历",
    "略历",
    "来历",
    "生涯",
    "生平",
    "career",
    "biography",
)

_AV_OCCUPATIONS: frozenset[str] = frozenset(
    {
        "Q1079215",  # AV女優 / AV idol
        "Q8380347",  # AV男優
        "Q488111",  # ポルノ俳優 / pornographic film actor / 色情演員
    }
)

# Wikidata P21 (sex or gender)
_P21_GENDER: dict[str, str] = {
    "Q6581072": "female",
    "Q6581097": "male",
}

# Wikidata 的厘米单位；其它单位的量值不换算，一律丢弃。
_CENTIMETRE = "http://www.wikidata.org/entity/Q174728"

# Wikidata 属性 → Emby ProviderIds 键（大小写沿用 Emby/Jellyfin 惯例）。
_PROVIDER_KEY_MAP: dict[str, str] = {
    "wikidata": "Wikidata",
    "imdb": "Imdb",
    "tmdb": "Tmdb",
    "twitter": "Twitter",
    "instagram": "Instagram",
    "fanza": "Fanza",
    "xhamster": "xHamster",
}

# 简介分段的标题按目标语言取：日文模式下与维基日文词条一致（個人情報 / 外部リンク）。
_SECTION_TITLES: dict[str, tuple[str, str]] = {
    "zh-cn": ("个人资料", "外部链接"),
    "zh-hant": ("個人資料", "外部連結"),
    "ja": ("個人情報", "外部リンク"),
}

# 资料段里的字段名：词条信息框缺失、只能由 Wikidata 拼时使用（日文模式不出现中文标签）。
_PROFILE_LABELS: dict[str, dict[str, str]] = {
    "zh-cn": {
        "birthday": "生日",
        "birthplace": "出生地",
        "height": "身高",
        "sizes": "三围",
        "cup": "罩杯",
        "alias": "别名",
    },
    "zh-hant": {
        "birthday": "生日",
        "birthplace": "出生地",
        "height": "身高",
        "sizes": "三圍",
        "cup": "罩杯",
        "alias": "別名",
    },
    "ja": {
        "birthday": "生年月日",
        "birthplace": "出身地",
        "height": "身長",
        "sizes": "スリーサイズ",
        "cup": "ブラサイズ",
        "alias": "別名",
    },
}

# 外部链接段：顺序与老实现（tools/wiki.py 的 url_log）一致，链接模板取各站的标准人页地址。
_PROVIDER_LINKS: tuple[tuple[str, str, str], ...] = (
    ("tmdb", "TheMovieDb", "https://www.themoviedb.org/person/{}"),
    ("imdb", "IMDb", "https://www.imdb.com/name/{}"),
    ("twitter", "Twitter", "https://twitter.com/{}"),
    ("instagram", "Instagram", "https://www.instagram.com/{}"),
    ("fanza", "Fanza", "https://actress.dmm.co.jp/-/detail/=/actress_id={}"),
    ("xhamster", "xHamster", "https://xhamster.com/pornstars/{}"),
)


class WikiSourceError(Exception):
    """维基请求失败（网络 / 解析）。与「未收录」区分，供调用方记日志。"""


@dataclass(slots=True)
class WikiActorProfile:
    """从 Wikidata + Wikipedia 得到的一份演员档案。"""

    name: str | None = None
    aliases: list[str] = field(default_factory=list)
    gender: str | None = None
    birthday: str | None = None
    birthplace: str | None = None
    height: int | None = None
    bust: int | None = None
    waist: int | None = None
    hip: int | None = None
    cup: str | None = None
    overview: str | None = None
    tagline: str | None = None
    image_url: str | None = None
    provider_ids: dict[str, str] = field(default_factory=dict)
    source_url: str = ""
    language: str = ""
    # 信息框原始行（label: value），保留血型/职业等结构化外的字段；
    # 有正文时由 apply_wiki_profile 拼进「个人资料」段。
    infobox: list[str] = field(default_factory=list)
    # 本次实际命中的检索名（可能是别名/旧名，与词条名不一定相同）；
    # 用于在简介「別名」行里同时体现旧名与新名。
    searched_name: str = ""

    @property
    def has_data(self) -> bool:
        return bool(
            self.birthday
            or self.birthplace
            or self.height
            or self.bust
            or self.waist
            or self.hip
            or self.cup
            or self.overview
            or self.tagline
            or self.provider_ids
            or self.image_url
        )


class _Figure(NamedTuple):
    height: int | None
    bust: int | None
    waist: int | None
    hip: int | None
    cup: str | None


_NO_FIGURE = _Figure(height=None, bust=None, waist=None, hip=None, cup=None)


class _WikiPage(NamedTuple):
    url: str
    language: str
    overview: str | None
    birthplace: str | None
    birthday: str | None
    figure: _Figure
    infobox: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------


async def fetch_wiki_actor(
    name: str,
    languages: Sequence[str] | None = None,
) -> WikiActorProfile | None:
    """按名字检索并抓取一份维基演员档案。

    ``languages`` 为空时读取 ``config.actor_wiki_languages``；未命中返回 ``None``，
    网络/解析失败抛 :class:`WikiSourceError`（调用方据此区分「未收录」与「连不上」）。
    """
    cleaned = (name or "").strip()
    if not cleaned:
        return None
    entry_languages = _entry_languages(languages)
    search_names = _actor_search_names(cleaned)
    for search_name in search_names:
        candidates = await _wikidata_search(search_name)
        for qid, desc in candidates:
            entity = await _entity_data(qid)
            if entity is None:
                continue
            if _is_av_entity(entity) and _name_matches_any(entity, search_names):
                profile = await _build_profile(qid, entity, desc, entry_languages, searched_name=search_name)
                if profile.has_data:
                    return profile
    return None


def apply_wiki_profile(
    actor_info: EMbyActressInfo,
    profile: WikiActorProfile,
    *,
    emby_on: Sequence[EmbyAction] | None = None,
) -> None:
    """把档案写进 ``EMbyActressInfo``（原地修改）。

    只写「维基给出了值」的字段；姓名始终保留 Emby 侧原值，不因词条语言改名。
    简介版式：词条导语（第一个段标题之前的部分）放在最上面，后面依次拼
    ``===== 个人资料 =====`` → ``===== 外部链接 =====`` → 人物 / 履历等正文章节
    （用户 2026-11-09：「导语放最上」——导语是「谁」的一句话概括，放最后会被当成
    外部链接列表的尾巴）。段标题与拼装字段名跟随目标语言，日文模式下即维基日文词条的
    「個人情報 / 外部リンク」。身高/三围/罩杯等 Emby 没有对应字段的信息一并进「个人资料」段。
    """
    from ..config.enums import EmbyAction

    actions = list(emby_on or manager.config.emby_on)
    target_lang = "zh-hant" if EmbyAction.ACTOR_INFO_ZH_TW in actions else "zh-cn"
    # 段标题与拼装字段名跟随目标语言：日文模式下即维基日文词条的「個人情報 / 外部リンク」。
    # 正文本身仍是词条原文（日文模式不翻译），故这里只管分段的标题与标签。
    section_lang = "ja" if EmbyAction.ACTOR_INFO_JA in actions else target_lang

    if profile.birthday:
        actor_info.birthday = profile.birthday
        actor_info.year = profile.birthday[:4]

    if profile.birthplace:
        place = _normalize_birthplace(profile.birthplace)
        if (
            profile.language == "ja"
            and EmbyAction.ACTOR_INFO_TRANSLATE in actions
            and EmbyAction.ACTOR_INFO_JA not in actions
        ):
            place = place.replace("県", "县")
            place = zhconv.convert(place, "zh-hant" if target_lang == "zh-hant" else "zh-cn")
        actor_info.locations = [f"日本·{place}"] if place else ["日本"]
    elif not actor_info.locations:
        actor_info.locations = ["日本"]

    for raw_key, value in profile.provider_ids.items():
        key = _PROVIDER_KEY_MAP.get(raw_key)
        if key and value:
            actor_info.provider_ids[key] = value

    if profile.tagline:
        tagline = profile.tagline.strip()
        if profile.language == "zh":
            tagline = zhconv.convert(tagline, target_lang)
        actor_info.taglines = [tagline]
        if profile.language in ("ja", "en") and EmbyAction.ACTOR_INFO_TRANSLATE in actions:
            actor_info.taglines_translate = True
    elif profile.language == "zh" and actor_info.taglines:
        actor_info.taglines = [zhconv.convert(str(actor_info.taglines[0]), target_lang)]

    profile_lines = _profile_lines(profile, section_lang)
    # 正文里的资料字段行归位：标签重复的删掉、缺的字段补进「个人资料」段末，
    # 整节都是资料字段时连标题与来源说明一起丢（实测亜紗美词条的「プロフィール」节）。
    overview, extra_fields = _split_profile_fields(profile.overview or "", profile_lines)
    profile_lines.extend(extra_fields)
    link_lines = _external_link_lines(profile)
    profile_title, link_title = _SECTION_TITLES.get(section_lang, _SECTION_TITLES["zh-cn"])
    lead, body = _split_lead(overview)
    blocks: list[str] = []
    # 导语排最上面：一句话介绍完「是谁」，后面才是资料 / 外链 / 正文章节。
    if lead:
        blocks.append(lead)
    if profile_lines:
        blocks.append(f"===== {profile_title} =====\n" + "\n".join(profile_lines))
    if link_lines:
        blocks.append(f"===== {link_title} =====\n" + "\n".join(link_lines))
    if body:
        blocks.append(body)
    overview = "\n\n".join(blocks)
    if overview:
        actor_info.overview = overview

    if profile.image_url and not getattr(actor_info, "avatar_url", ""):
        actor_info.avatar_url = profile.image_url
    if profile.source_url:
        actor_info.source_url = profile.source_url


# ---------------------------------------------------------------------------
# Wikidata 检索与实体校验
# ---------------------------------------------------------------------------


async def _wikidata_search(name: str) -> list[tuple[str, str | None]]:
    """ja/zh/en wbsearchentities；描述命中 AV 关键词者按语言顺序去重。"""
    out: dict[str, str | None] = {}
    last_error = ""
    for lang in _SEARCH_LANGUAGES:
        url = (
            f"https://www.wikidata.org/w/api.php?action=wbsearchentities&search={quote(name)}"
            f"&language={lang}&uselang={lang}&limit={_SEARCH_CANDIDATE_LIMIT}&format=json"
        )
        data, error = await _get_json(url)
        if data is None:
            last_error = error
            continue
        if not isinstance(data, dict):
            continue
        for item in data.get("search") or []:
            if not isinstance(item, dict):
                continue
            qid = item.get("id")
            if not (isinstance(qid, str) and qid.startswith("Q")) or qid in out:
                continue
            desc = str(item.get("description") or "")
            if not _match_av_keyword(desc):
                continue
            out[qid] = desc or None
    if not out and last_error:
        raise WikiSourceError(last_error)
    return list(out.items())


async def _entity_data(qid: str) -> dict[str, Any] | None:
    url = f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
    data, error = await _get_json(url)
    if data is None:
        raise WikiSourceError(error)
    if not isinstance(data, dict):
        return None
    entities = data.get("entities")
    if not isinstance(entities, dict):
        return None
    entity = entities.get(qid)
    return entity if isinstance(entity, dict) else None


async def _get_json(url: str) -> tuple[Any | None, str]:
    async with manager.acquire_computed() as computed:
        return await computed.async_client.get_json(url, headers=_wiki_headers())


async def _get_text(url: str) -> tuple[str | None, str]:
    async with manager.acquire_computed() as computed:
        # 正文用 get_text：引用里「年齢認証」等词会让 get_html 误判拦截。
        return await computed.async_client.get_text(url, headers=_wiki_headers())


def _match_av_keyword(description: str) -> bool:
    lower = description.lower()
    if any(k.lower() in lower for k in _AV_KEYWORDS):
        return True
    return bool(_AV_INDUSTRY_RE.search(description) and _AV_ROLE_RE.search(description))


def _is_av_entity(entity: dict[str, Any]) -> bool:
    return _descriptions_match(entity) or _occupation_match(entity)


def _name_matches(entity: dict[str, Any], name: str) -> bool:
    """实体名（标签或别名，任一语言）与查找名 NFKC 折叠后相等才算命中。

    ``wbsearchentities`` 是模糊检索：只按描述与职业筛实体，会把名字完全不同的他人档案当成本人。
    """
    return any(_is_same_name(value, name) for value in _entity_name_values(entity))


def _name_matches_any(entity: dict[str, Any], names: Sequence[str]) -> bool:
    """实体名与任一候选写法相等即命中（覆盖日文名 / 简繁 / 本地库别名）。"""
    return any(_name_matches(entity, name) for name in names if name)


def _actor_search_names(name: str) -> list[str]:
    """构造检索名候选：原名 → 本地库日文名/繁中名/别名 → 繁体回退。

    维基检索对简繁和日文写法很敏感（如「三上悠亞 / 三上悠亜」），本地演员库
    已经把三种写法和别名准备好了，直接拿来逐个尝试比反复请求翻译接口更可靠。
    """
    names = [name]
    try:
        data = resources.get_actor_data(name)
        for key in ("jp", "zh_tw", "zh_cn"):
            value = str(data.get(key) or "").strip()
            if value and value not in names:
                names.append(value)
        for value in data.get("keyword") or []:
            value = str(value).strip()
            if value and value not in names:
                names.append(value)
    except Exception:
        pass
    if len(names) == 1:
        converted = zhconv.convert(name, "zh-hant")
        if converted and converted not in names:
            names.append(converted)
    return names


def _entity_name_values(entity: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in ("labels", "aliases"):
        groups = entity.get(key)
        if not isinstance(groups, dict):
            continue
        for items in groups.values():
            for item in items if isinstance(items, list) else [items]:
                value = item.get("value") if isinstance(item, dict) else None
                if isinstance(value, str) and value.strip():
                    out.append(value)
    return out


def _descriptions_match(entity: dict[str, Any]) -> bool:
    descs = entity.get("descriptions")
    if not isinstance(descs, dict):
        return False
    for item in descs.values():
        if isinstance(item, dict) and isinstance(item.get("value"), str) and _match_av_keyword(item["value"]):
            return True
    return False


def _occupation_match(entity: dict[str, Any]) -> bool:
    claims = entity.get("claims")
    if not isinstance(claims, dict):
        return False
    entries = claims.get("P106")
    if not isinstance(entries, list):
        return False
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        snak = entry.get("mainsnak")
        if not isinstance(snak, dict):
            continue
        datavalue = snak.get("datavalue")
        if not isinstance(datavalue, dict):
            continue
        value = datavalue.get("value")
        if isinstance(value, dict) and value.get("id") in _AV_OCCUPATIONS:
            return True
    return False


# ---------------------------------------------------------------------------
# 档案构建
# ---------------------------------------------------------------------------


async def _build_profile(
    qid: str,
    entity: dict[str, Any],
    tagline: str | None,
    languages: tuple[str, ...],
    searched_name: str = "",
) -> WikiActorProfile:
    labels_raw = entity.get("labels")
    labels: dict[str, Any] = labels_raw if isinstance(labels_raw, dict) else {}
    preferred = _prefer_label(labels)
    aliases = [a for a in _label_aliases(labels) if a != preferred]
    birthday = _claim_time(entity, "P569")
    gender = _claim_gender(entity)
    image_url = _claim_commons_image(entity)
    provider_ids = _provider_ids(qid, entity)
    sitelinks_raw = entity.get("sitelinks")
    sitelinks: dict[str, Any] = sitelinks_raw if isinstance(sitelinks_raw, dict) else {}

    overview: str | None = None
    birthplace: str | None = None
    source_url: str | None = None
    page_language = ""
    figure = _NO_FIGURE
    infobox: list[str] = []
    page = await _fetch_wiki_page(sitelinks, languages)
    if page is not None:
        source_url = page.url
        page_language = page.language
        overview = page.overview
        birthplace = page.birthplace
        figure = page.figure
        infobox = list(page.infobox)
        if not birthday:
            birthday = page.birthday

    # 身高另有 Wikidata P2048；信息框所在词条优先于实体声明。
    height = figure.height if figure.height is not None else _claim_quantity(entity, "P2048", unit=_CENTIMETRE)

    if not source_url:
        source_url = f"https://www.wikidata.org/wiki/{qid}"

    if not tagline:
        tagline = _preferred_description(entity, languages)
    elif page_language == "zh":
        tagline = zhconv.convert(tagline, "zh-cn")

    return WikiActorProfile(
        name=preferred,
        aliases=aliases,
        gender=gender,
        birthday=birthday,
        birthplace=birthplace,
        height=height,
        bust=figure.bust,
        waist=figure.waist,
        hip=figure.hip,
        cup=figure.cup,
        overview=overview,
        tagline=tagline,
        image_url=image_url,
        provider_ids=provider_ids,
        source_url=source_url,
        language=page_language,
        infobox=infobox,
        searched_name=searched_name,
    )


async def _fetch_wiki_page(
    sitelinks: dict[str, Any],
    languages: tuple[str, ...],
) -> _WikiPage | None:
    """按配置的语言优先级取第一个有正文的词条。

    单语言失败不阻断；全部失败时抛最后一次错误。各语言的词条都没有正文时，
    仍返回优先级最高的可解析词条，信息框字段照常取用。
    """
    fallback: _WikiPage | None = None
    last_error = ""
    for lang in languages:
        url = _wiki_url(sitelinks, lang)
        if url is None:
            continue
        html, error = await _get_text(url)
        if html is None:
            last_error = error
            continue
        if not html:
            continue
        page = _parse_wiki_page(url, lang, html)
        if page.overview:
            return page
        if fallback is None:
            fallback = page
    if fallback is None and last_error:
        raise WikiSourceError(last_error)
    return fallback


def _entry_languages(languages: Sequence[str] | None) -> tuple[str, ...]:
    if languages is None:
        languages = getattr(manager.config, "actor_wiki_languages", None) or WIKI_LANGUAGES
    ordered = tuple(dict.fromkeys(str(lang).strip().lower() for lang in languages))
    allowed = tuple(lang for lang in ordered if lang in WIKI_LANGUAGES)
    return allowed or WIKI_LANGUAGES


def _wiki_url(sitelinks: dict[str, Any], lang: str) -> str | None:
    link = sitelinks.get(f"{lang}wiki")
    title = link.get("title") if isinstance(link, dict) else None
    if not isinstance(title, str) or not title:
        return None
    prefix = _WIKI_VARIANTS.get(lang, "wiki")
    return f"https://{lang}.wikipedia.org/{prefix}/{quote(title.replace(' ', '_'), safe='()_')}"


def _preferred_description(entity: dict[str, Any], languages: tuple[str, ...]) -> str | None:
    descs_raw = entity.get("descriptions")
    descs: dict[str, Any] = descs_raw if isinstance(descs_raw, dict) else {}
    candidates = list(languages) + ["zh", "zh-cn", "zh-tw", "ja", "en"]
    for lang in dict.fromkeys(candidates):
        item = descs.get(lang)
        if isinstance(item, dict) and item.get("value"):
            return str(item["value"])
    return None


def _prefer_label(labels: dict[str, Any]) -> str | None:
    for lang in ("ja", "zh", "zh-cn", "zh-tw", "en"):
        item = labels.get(lang)
        if isinstance(item, dict) and item.get("value"):
            return str(item["value"])
    for item in labels.values():
        if isinstance(item, dict) and item.get("value"):
            return str(item["value"])
    return None


def _label_aliases(labels: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for lang in ("ja", "zh", "zh-cn", "zh-tw", "en"):
        item = labels.get(lang)
        if not isinstance(item, dict):
            continue
        val = str(item.get("value") or "").strip()
        if val and val not in seen:
            seen.add(val)
            out.append(val)
    return out


def _claim_time(entity: dict[str, Any], pid: str) -> str | None:
    claims = entity.get("claims")
    if not isinstance(claims, dict):
        return None
    entries = claims.get(pid)
    if not isinstance(entries, list) or not entries:
        return None
    snak = entries[0].get("mainsnak") if isinstance(entries[0], dict) else None
    if not isinstance(snak, dict):
        return None
    datavalue = snak.get("datavalue")
    if not isinstance(datavalue, dict):
        return None
    value = datavalue.get("value")
    if not isinstance(value, dict):
        return None
    time = value.get("time")
    if not isinstance(time, str):
        return None
    # +1994-08-26T00:00:00Z
    m = re.match(r"[+-]?(\d{4})-(\d{2})-(\d{2})", time)
    if not m:
        return None
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


def _claim_quantity(entity: dict[str, Any], pid: str, *, unit: str) -> int | None:
    """取单条 quantity 声明的整数值；单位不是 ``unit`` 的量值返回 ``None``。"""
    claims = entity.get("claims")
    if not isinstance(claims, dict):
        return None
    entries = claims.get(pid)
    if not isinstance(entries, list) or not entries:
        return None
    snak = entries[0].get("mainsnak") if isinstance(entries[0], dict) else None
    if not isinstance(snak, dict):
        return None
    datavalue = snak.get("datavalue")
    if not isinstance(datavalue, dict):
        return None
    value = datavalue.get("value")
    if not isinstance(value, dict) or value.get("unit") != unit:
        return None
    amount = value.get("amount")
    if not isinstance(amount, str):
        return None
    try:
        number = float(amount)
    except ValueError:
        return None
    return int(number) if number.is_integer() else None


def _claim_gender(entity: dict[str, Any]) -> str | None:
    claims = entity.get("claims")
    if not isinstance(claims, dict):
        return None
    entries = claims.get("P21")
    if not isinstance(entries, list) or not entries:
        return None
    snak = entries[0].get("mainsnak") if isinstance(entries[0], dict) else None
    if not isinstance(snak, dict):
        return None
    datavalue = snak.get("datavalue")
    if not isinstance(datavalue, dict):
        return None
    value = datavalue.get("value")
    if not isinstance(value, dict):
        return None
    qid = value.get("id")
    if not isinstance(qid, str):
        return None
    return _P21_GENDER.get(qid)


def _claim_commons_image(entity: dict[str, Any]) -> str | None:
    claims = entity.get("claims")
    if not isinstance(claims, dict):
        return None
    entries = claims.get("P18")
    if not isinstance(entries, list) or not entries:
        return None
    snak = entries[0].get("mainsnak") if isinstance(entries[0], dict) else None
    if not isinstance(snak, dict):
        return None
    datavalue = snak.get("datavalue")
    if not isinstance(datavalue, dict):
        return None
    filename = datavalue.get("value")
    if not isinstance(filename, str) or not filename.strip():
        return None
    # Special:FilePath 会 302 到实际 upload URL；空格等必须编码。
    return f"https://commons.wikimedia.org/wiki/Special:FilePath/{quote(filename.strip())}"


def _provider_ids(qid: str, entity: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {"wikidata": qid}
    claims = entity.get("claims")
    if not isinstance(claims, dict):
        return out
    mapping = {
        "P345": "imdb",
        "P4985": "tmdb",
        "P2002": "twitter",
        "P2003": "instagram",
        "P9781": "fanza",
        "P8720": "xhamster",
    }
    for pid, key in mapping.items():
        entries = claims.get(pid)
        if not isinstance(entries, list) or not entries:
            continue
        snak = entries[0].get("mainsnak") if isinstance(entries[0], dict) else None
        if not isinstance(snak, dict):
            continue
        datavalue = snak.get("datavalue")
        if not isinstance(datavalue, dict):
            continue
        val = datavalue.get("value")
        if isinstance(val, str) and val:
            out[key] = val
    return out


# ---------------------------------------------------------------------------
# HTML 解析
# ---------------------------------------------------------------------------


def _parse_wiki_page(url: str, language: str, html_text: str) -> _WikiPage:
    html = Selector(text=html_text)
    overview = "\n\n".join(_overview_blocks(html)) or None
    birthplace, birthday, figure, infobox = _parse_infobox(html)
    return _WikiPage(
        url=url,
        language=language,
        overview=overview,
        birthplace=birthplace,
        birthday=birthday,
        figure=figure,
        infobox=tuple(infobox),
    )


def _overview_blocks(html: Selector) -> list[str]:
    """导语段落 + 白名单章节的段落与列表；表格内的段落（信息框 / 导航框）不取。

    标题层级决定归属：白名单章节层级以下的子章节同属该章节，遇到同级或更高级标题才退出。
    输出顺序固定为「导语 → 人物类章节 → 经历类章节 → 其它白名单章节」，同类内保持
    原文顺序（用户 2026-11-08：正文要包含人物与经历，且先人物再经历）。

    章节之间插入 `===== 标题 =====` 行（标题取维基原文，如「人物」「経歴」）：
    段序重排后人物段与经历段紧邻，只靠空行分不开归属，用户反馈「经历 人物 没有
    分割符号」（2026-11-08）。导语无标题，不加。

    子标题同样保留：`== 人物 ==` 下面的 `=== AV新法への反対 ===` 是页面上的独立小标题，
    此前被当作「同属人物章节」直接吞掉，正文里只剩空行、看不出小节边界（用户 2026-11-09：
    「AV新法への反対 h3 没有」）。现在只要祖先里有白名单章节，就按**最内层标题**出段标题，
    以 `=` 的个数体现层级（h2 五个、h3 四个，依此类推）。
    """
    collected: list[tuple[int, int, int, str, str]] = []
    seq = 0

    def add(text: str) -> None:
        nonlocal seq
        depth, block_title = _block_heading(headings)
        collected.append((_section_group(headings), seq, depth, block_title, text))
        seq += 1

    headings: list[tuple[int, str]] = []
    selected = True
    for node in html.css(_PARSER_OUTPUT).xpath(_CONTENT_NODES):
        tag = node.root.tag
        if not isinstance(tag, str):
            continue
        if tag in _HEADING_TAGS:
            title = _heading_text(node)
            if title:
                level = int(tag[1])
                while headings and headings[-1][0] >= level:
                    headings.pop()
                headings.append((level, title))
                selected = any(_is_section(name) for _, name in headings)
            continue
        if not selected or _has_ancestor(node.root, _SKIP_WRAPPERS):
            continue
        if tag == "p":
            # 列表里的段落随整块列表取用，不重复。
            if _has_ancestor(node.root, _LIST_TAGS):
                continue
            text = _clean_text(node)
            if text:
                add(text)
            continue
        if _has_ancestor(node.root, _LIST_TAGS):
            continue
        items = [text for text in (_clean_text(item) for item in node.xpath("./li")) if text]
        if items:
            add("\n".join(items))
    collected.sort(key=lambda item: (item[0], item[1]))

    # 相邻同标题段落并成一段，标题只在切换时写一次；标题或深度变了就另起一段。
    chunks: list[str] = []
    heading: tuple[int, str] = (0, "")
    paragraphs: list[str] = []
    for _group, _seq, depth, block_title, text in collected:
        if (depth, block_title) != heading:
            if paragraphs:
                chunks.append(_body_chunk(heading, paragraphs))
            heading = (depth, block_title)
            paragraphs = []
        paragraphs.append(text)
    if paragraphs:
        chunks.append(_body_chunk(heading, paragraphs))
    return chunks


def _body_chunk(heading: tuple[int, str], paragraphs: list[str]) -> str:
    """一段正文：有章节标题时先写标题行，段落之间空一行。

    标题用等号包裹，个数随**章节内深度**递减（白名单章节本身 `===== 人物 =====`，
    它下面的子标题 `==== AV新法への反対 ====`）。深度而不是维基层级：`小传 → 人物`
    这种「人物 被包在未收录章节里」的词条，段标题仍应是五级。
    """
    body = "\n\n".join(paragraphs)
    depth, title = heading
    if not title:
        return body
    marker = "=" * max(2, 6 - depth)
    return f"{marker} {title} {marker}\n{body}"


def _heading_text(node: Selector) -> str:
    text = _EDIT_LINK_RE.sub("", "".join(node.xpath(".//text()").getall()))
    return re.sub(r"\s+", " ", text).strip()


def _is_section(title: str) -> bool:
    folded = _section_fold(title)
    return any(keyword in folded for keyword in _SECTION_KEYWORDS)


def _section_fold(title: str) -> str:
    """章节标题折叠：中文繁体转简体 + 日文汉字归一 + 小写，供关键字比对。"""
    return zhconv.convert(title, "zh-cn").translate(_JA_HEADING_FOLD).lower()


def _section_title(headings: list[tuple[int, str]]) -> str:
    """当前段落所属的白名单章节标题（取最内层）；导语返回空串。"""
    return next((name for _level, name in reversed(headings) if _is_section(name)), "")


def _block_heading(headings: list[tuple[int, str]]) -> tuple[int, str]:
    """段落输出用的段标题：(章节内深度, 标题)；导语返回 ``(0, "")``。

    只要祖先里出现白名单章节，就取**最内层标题**（含非白名单子标题），深度从**最外层**
    白名单标题算起（1 = 章节本身，2 = 它下面的子章节/子标题）。子标题保留是刻意的：
    `== 人物 ==` 下的 `=== AV新法への反対 ===` 在页面上是独立小节，吞掉它正文就只剩
    空行分隔；`小传 → 人物` 这种两级白名单章节也照页面显示成二级。
    """
    for index, (_level, title) in enumerate(headings):
        if _is_section(title):
            return len(headings) - index, headings[-1][1]
    return 0, ""


def _section_group(headings: list[tuple[int, str]]) -> int:
    """段落归属分组：0=导语（无标题）、1=人物类、2=经历类、3=其它白名单章节。

    取**最内层**的白名单标题作为归属：`== 人物 ==` 下的 `=== 略歴 ===` 归经历，
    同一章节下再分的子章节各自按自己的标题归类。
    """
    section = _section_title(headings)
    if not section:
        return 3 if headings else 0
    folded = _section_fold(section)
    if any(keyword in folded for keyword in _PERSON_SECTIONS):
        return 1
    if any(keyword in folded for keyword in _HISTORY_SECTIONS):
        return 2
    return 3


_TEXT_SKIP_TAGS = frozenset({"style", "script"})
# 列表项在维基里靠 CSS 生成分隔符（hlist 模板），取文本时要自己断行
_TEXT_BREAK_TAGS = frozenset({"br", "li", "dd", "dt"})


def _iter_text_parts(root: Any):
    """按文档序产出文本片段：`<br>` / 列表项处产出换行，`<style>`/`<script>` 内容丢弃。

    维基的 hlist 模板会把 `display:inline` 的样式表一并写进单元格，直接拼
    `.//text()` 会把整段 CSS 当成字段值（实测音琴るい词条的「専属契約」）。
    parsel 的 text() 结果未必带 `getparent()`，这里直接用 lxml 元素树遍历并在源头跳过。
    """
    if not isinstance(root.tag, str) or root.tag in _TEXT_SKIP_TAGS:
        return
    if root.tag in _TEXT_BREAK_TAGS:
        yield "\n"
    if root.text:
        yield root.text
    for child in root:
        if not isinstance(child.tag, str):
            if child.tail:
                yield child.tail
            continue
        yield from _iter_text_parts(child)
        if child.tail:
            yield child.tail


def _clean_text(node: Selector) -> str:
    """节点文本：`<br>` 与列表项一律断行，去引用标记并收拢每行内的空白。

    维基正文常把一个段落里的多行（作品列表、逐条履历）用 `<br>` 分隔，直接拼接
    `.//text()` 会把它们并成一整行——页面上明明分行，刮下来的简介却没有换行。
    因此按「文本 / `<br>` / 列表项」文档序逐个收集，断行处插入换行，再逐行收拢空白；
    行内空白仍压成一个空格（与 `_clean_inline` 同口径），空行直接丢弃。
    """
    text = _strip_archive_notes(_CITATION_RE.sub("", "".join(_iter_text_parts(node.root))))
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def _clean_inline(text: str) -> str:
    return re.sub(r"\s+", " ", _strip_archive_notes(_CITATION_RE.sub("", text))).strip()


def _strip_archive_notes(text: str) -> str:
    """删除存档标注、引用访问日期与参考文献定位标记。"""
    clauses: list[tuple[re.Match[str], int]] = []
    for pattern, priority in ((_ARCHIVE_BRACKET_RE, 0), (_ACCESS_DATE_RE, 1), (_ARCHIVE_TAIL_RE, 2)):
        clauses += [(m, priority) for m in pattern.finditer(text)]
    clauses.sort(key=lambda item: (item[0].start(), item[1], -item[0].end()))

    kept: list[str] = []
    kept_len = 0
    cuts: list[int] = []
    pos = 0
    for match, _ in clauses:
        if match.start() < pos:
            continue
        kept.append(text[pos : match.start()])
        kept_len += match.start() - pos
        cuts.append(kept_len - 1)
        pos = match.end()
    kept.append(text[pos:])
    text = "".join(kept)

    def tidy(match: re.Match[str]) -> str:
        return "" if any(cut <= match.start() <= cut + 1 for cut in cuts) else match.group(0)

    text = _TIDY_PUNCT_RE.sub(tidy, text) if cuts else text
    return _REF_MARKER_RE.sub("", _EMPTY_BRACKET_RE.sub("", text))


def _has_ancestor(node: Any, tags: frozenset[str]) -> bool:
    """向上查找祖先；到 ``.mw-parser-output`` 即停，范围外的节点不参与判定。"""
    for ancestor in node.iterancestors():
        tag = ancestor.tag
        if not isinstance(tag, str):
            continue
        if tag in tags:
            return True
        if tag == "div" and _PARSER_OUTPUT_CLASS in (ancestor.get("class") or ""):
            return False
    return False


# 标签随词条语言一套：中文（简体）与日文。繁体渲染只出现在 zh-tw 变体，而中文词条固定取 zh-cn，因此不收。
_HEIGHT_LABELS: tuple[str, ...] = ("身長", "身高")
_SIZES_LABELS: tuple[str, ...] = ("スリーサイズ", "三围")
_CUP_LABELS: tuple[str, ...] = ("ブラサイズ", "罩杯")
# 识别「人物信息框」用的行标签：词条里可能同时有 YouTube 频道 / 歌手 等其它 infobox。
_BIRTH_LABELS: tuple[str, ...] = ("生年月日", "生年", "生誕", "出生")
_ALIAS_LABELS: tuple[str, ...] = ("別名", "别名", "愛称", "爱称", "ニックネーム", "昵称")
# 「別名」类标签：搜索名 / 词条名要补进这一行（愛称不加）
_ALIAS_NAME_LABELS: tuple[str, ...] = ("別名", "别名")
_PLACE_LABELS: tuple[str, ...] = ("出身地", "出生地")
# 信息框底部的「计量单位换算 / 英米単位系」折叠块渲染出同名的英制行（5英尺3英寸 / 32 - 23 - 34 英寸）。
# 单位不可省：只认公制，否则英寸会被当厘米写进身高与三围。
_METRIC = r"(?:cm|厘米)"
_CM = r"(\d{2,3}(?:\.\d+)?)"
_HEIGHT_RE = re.compile(rf"^{_CM}\s*{_METRIC}")
_SIZES_RE = re.compile(rf"^{_CM}\s*-\s*{_CM}\s*-\s*{_CM}\s*{_METRIC}")
# 英制行（5 ft 3 in / 32 - 23 - 33 in / ― lb）只在「表示英米単位系」折叠块里出现，
# 展开后是身長/体重、スリーサイズ 的重复行；简介里同名字段一律保留公制那一条。
_IMPERIAL_LABEL = "単位系"
_IMPERIAL_VALUE_RE = re.compile(r"\d\s*(?:ft|in)\b|\blb\b|フィート|インチ", re.IGNORECASE)
# 罩杯是字母加可选下标：C / C70 / C-65（下标为下胸围）。
_CUP_RE = re.compile(r"^([A-Za-z]{1,2})\s*-?\s*\d{0,3}$")


def _round_cm(raw: str) -> int:
    """长度取整到厘米；信息框偶尔写小数（深田えいみ的三围），四舍五入而非丢弃。"""
    return math.floor(float(raw) + 0.5)


def _fill_figure(figure: _Figure, label: str, value: str) -> _Figure:
    """按标签填空：取第一条解析得出的值，同名行不覆盖（英制换算是同名行的后手）。"""
    text = _clean_inline(value)
    if figure.height is None and any(keyword in label for keyword in _HEIGHT_LABELS):
        match = _HEIGHT_RE.match(text)
        return figure._replace(height=_round_cm(match.group(1))) if match else figure
    if figure.bust is None and any(keyword in label for keyword in _SIZES_LABELS):
        match = _SIZES_RE.match(text)
        if match:
            return figure._replace(
                bust=_round_cm(match.group(1)),
                waist=_round_cm(match.group(2)),
                hip=_round_cm(match.group(3)),
            )
        return figure
    if figure.cup is None and any(keyword in label for keyword in _CUP_LABELS):
        match = _CUP_RE.match(text)
        return figure._replace(cup=match.group(1).upper()) if match else figure
    return figure


def _extract_text(node: Selector, xpath: str) -> str:
    values = node.xpath(xpath).getall()
    return values[0] if values else ""


def _cell_text(row: Selector, tag: str) -> str:
    """单元格文本：把 `<br>` 当行分隔。

    信息框里多个值常用 `<br />` 分行（如別名：`上村陽菜（…）<br />CHIAKI／Chiaki（…）`），
    旧的 `string(.//td)` 直接把各行粘在一起，既没分隔也读不出来。这里逐个收集
    「文本 / `<br>`」，`<br>` 处输出 `\n`，交给下游按行清洗后拼成一行。
    """
    cells = row.xpath(f"./{tag}") or row.xpath(f".//{tag}")
    if not cells:
        return ""
    return "".join(_iter_text_parts(cells[0].root)).strip()


def _join_cell_lines(value: str) -> str:
    """单元格里的多行合成一行：逐行清洗后用「、」分隔（去重、去空、去多余顿号）。

    以括号开头的行是上一项的补充（维基习惯 `S1 NO.1 STYLE<br>（2014年7月 - 2020年3月）`），
    直接接到上一项后面，不加顿号。
    """
    parts: list[str] = []
    for line in value.split("\n"):
        text = _clean_inline(line)
        if not text:
            continue
        if parts and text[0] in "（(":
            if not parts[-1].endswith(text):
                parts[-1] = f"{parts[-1]}{text}"
            continue
        if text not in parts:
            parts.append(text)
    return re.sub(r"、{2,}", "、", "、".join(parts)).strip("、 ")


def _main_infobox(html: Selector) -> Selector | None:
    """取人物信息框：优先「含生年/別名/出身地」的第一个 infobox。

    词条常带多个 infobox（人物 + YouTube 频道 + 歌手），全收会把订阅数、唱片公司
    之类的无关行塞进「个人资料」段（实测天使もえ词条 30 行、其中一半是别的表）。
    """
    tables = [table for table in html.css("table.infobox") if isinstance(table.root.tag, str)]
    for table in tables:
        labels = " ".join(table.xpath(".//th//text()").getall())
        if any(key in labels for key in (*_BIRTH_LABELS, *_ALIAS_LABELS, *_PLACE_LABELS)):
            return table
    return tables[0] if tables else None


def _parse_infobox(html: Selector) -> tuple[str | None, str | None, _Figure, list[str]]:
    """信息框的出身地、出生日期、身材与原始行；与词条语言无关，命中即取。"""
    birthplace = None
    birthday = None
    figure = _NO_FIGURE
    rows: list[str] = []
    seen_rows: set[str] = set()
    seen_labels: set[str] = set()
    box = _main_infobox(html)
    if box is None:
        return birthplace, birthday, figure, rows
    for row in box.css("tr"):
        # 主信息框里常嵌着别的 infobox（如YouTube频道：登録者数/総再生回数），
        # 只取「最近祖先表就是主信息框」的行，嵌套表的行一律跳过
        owner = next(iter(row.root.iterancestors("table")), None)
        if owner is not box.root:
            continue
        label = re.sub(r"\s+", " ", _cell_text(row, "th")).strip()
        value = _cell_text(row, "td")
        if not label or not value:
            continue
        # 「表示英米単位系」折叠块及其展开后的英制同名行（5 ft 3 in / 32 - 23 - 33 in）
        # 不是新字段，简介里同名字段保留公制那一条
        if _IMPERIAL_LABEL in label:
            continue
        # 同名字段只留第一次出现的（现名在前、内嵌模板在后）
        if label in seen_labels:
            continue
        seen_labels.add(label)
        clean_value = _join_cell_lines(value)
        # 日文 infobox 会把 <span class="bday"> 的 ISO 日期再渲染一遍：
        # 「(1971-01-19)1971年1月19日（55歳）」，去掉括号里的重复 ISO 日期。
        clean_value = re.sub(r"^\s*[（(]\d{4}-\d{2}-\d{2}[）)]\s*", "", clean_value)
        line = f"{label}: {clean_value}"
        if line not in seen_rows:
            seen_rows.add(line)
            rows.append(line)
        if ("出身" in label or "出生地" in label) and not birthplace:
            birthplace = clean_value
        if ("生年" in label or "出生" in label) and not birthday:
            birthday = _normalize_calendar_date(value)
        figure = _fill_figure(figure, label, value)
    return birthplace, birthday, figure, rows


# ---------------------------------------------------------------------------
# 通用小工具（与 amane 同名函数的本地副本，避免把整包依赖带进来）
# ---------------------------------------------------------------------------

_DATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})(?:[Tt\s].*)?$"),
    re.compile(r"^(?P<y>\d{4})[-/.](?P<m>\d{1,2})[-/.](?P<d>\d{1,2})$"),
    re.compile(r"(?P<y>\d{4})\s*年\s*(?P<m>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*日"),
)


def _normalize_calendar_date(value: str | None) -> str | None:
    if value is None:
        return None
    text = unicodedata.normalize("NFKC", value).strip()
    if not text:
        return None
    if text.startswith("+"):
        text = text[1:].lstrip()
    for pattern in _DATE_PATTERNS:
        match = pattern.fullmatch(text) if pattern.pattern.startswith("^") else pattern.search(text)
        if not match:
            continue
        year, month, day = int(match.group("y")), int(match.group("m")), int(match.group("d"))
        if not _valid_ymd(year, month, day):
            return None
        return f"{year:04d}-{month:02d}-{day:02d}"
    return None


def _valid_ymd(year: int, month: int, day: int) -> bool:
    if year < 1 or year > 9999 or month < 1 or month > 12 or day < 1:
        return False
    return day <= calendar.monthrange(year, month)[1]


def _normalize_name(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip()


def _fold_name(value: str) -> str:
    return _normalize_name(value).casefold()


def _is_same_name(left: str, right: str) -> bool:
    return bool(left) and bool(right) and _fold_name(left) == _fold_name(right)


def _normalize_birthplace(value: str) -> str:
    place = value.split("→")[0].strip()
    place = re.sub(r"^日本[\s・·,，、]*", "", place)
    place = place.replace("日本・", "").replace("日本·", "").strip()
    # 纯 CJK/假名地名去掉词间空白，避免「福岛县 いわき市」这种排版空格入库。
    if place and not re.search(r"[A-Za-z0-9]", place):
        place = re.sub(r"\s+", "", place)
    return place


def _alias_key(value: str) -> str:
    """名字去重键：NFKC + 去空白 + 只看括号前的名字主体（括号里是读音/罗马音）。"""
    text = unicodedata.normalize("NFKC", value)
    text = re.split(r"[(（]", text, maxsplit=1)[0]
    return re.sub(r"\s+", "", text).casefold()


def _extra_alias_names(profile: WikiActorProfile) -> list[str]:
    """需要补进「別名」行的名字：搜索名与词条名不同时，两个都算该演员用过的名字。

    搜别名命中现名词条（のあういか → 桃愛ゆえ）→ 补现名；
    词条仍是旧名（桃愛ゆえ → のあういか）→ 补搜索名。两边都不同则都补。
    """
    searched = (profile.searched_name or "").strip()
    entry = (profile.name or "").strip()
    if not searched or not entry or _alias_key(searched) == _alias_key(entry):
        return []
    return [searched, entry]


def _merge_alias_value(value: str, extra: list[str], drop: str = "") -> str:
    """在「A、B、C」形式的別名值上补名字，并去掉与搜索名同形的项。

    `drop` 是本次检索用的名字：用户按 A 搜的，A 再列进「別名」纯属重复。
    """
    parts = [part.strip() for part in value.split("、") if part.strip()]
    if drop:
        parts = [part for part in parts if _alias_key(part) != drop]
    seen = {_alias_key(part) for part in parts}
    for name in extra:
        key = _alias_key(name)
        if key and key != drop and key not in seen:
            seen.add(key)
            parts.append(name)
    return "、".join(parts)


def _profile_lines(profile: WikiActorProfile, lang: str = "zh-cn") -> list[str]:
    """「个人资料」段的每行一个字段；词条有信息框时直接沿用原文行（日文词条即日文标签）。

    多值字段（別名 / 愛称）保持一行，值之间用「、」分隔（在 `_join_cell_lines` 里拼好）。
    「別名」行额外补上搜索名/词条名：信息框常只列旧名，现名（词条名）反而不在里面。
    """
    labels = _PROFILE_LABELS.get(lang, _PROFILE_LABELS["zh-cn"])
    alias_label = labels["alias"]
    extra = _extra_alias_names(profile)
    drop = _alias_key(profile.searched_name) if profile.searched_name else ""
    if profile.infobox:
        lines: list[str] = []
        for line in profile.infobox:
            label, sep, value = line.partition(": ")
            if sep and label in _ALIAS_NAME_LABELS:
                merged = _merge_alias_value(value, extra, drop)
                if not merged:
                    continue
                line = f"{label}: {merged}"
            lines.append(line)
        if profile.aliases and not any(line.partition(": ")[0] in _ALIAS_NAME_LABELS for line in lines):
            names = [name for name in dict.fromkeys(list(profile.aliases) + extra) if _alias_key(name) != drop]
            if names:
                lines.append(f"{alias_label}: {'、'.join(names)}")
        return lines
    lines = []
    if profile.birthday:
        lines.append(f"{labels['birthday']}: {profile.birthday}")
    if profile.birthplace:
        lines.append(f"{labels['birthplace']}: {profile.birthplace}")
    if profile.height:
        lines.append(f"{labels['height']}: {profile.height}cm")
    sizes = [value for value in (profile.bust, profile.waist, profile.hip) if value]
    if sizes:
        lines.append(f"{labels['sizes']}: {' - '.join(str(value) for value in sizes)}")
    if profile.cup:
        lines.append(f"{labels['cup']}: {profile.cup}")
    names = [name for name in dict.fromkeys(list(profile.aliases) + extra) if _alias_key(name) != drop]
    if names:
        lines.append(f"{alias_label}: {'、'.join(names)}")
    return lines


# 正文里形如「标签: 值」的资料行。标签不收数字：避免把「2005年1月: …」这类时间轴
# 当成字段；值以 URL 开头的同样不算（正文不该出现外链行，错误归位反而更脏）。
_BODY_FIELD_RE = re.compile(r"^\s*(?P<label>[^:：\d\n]{1,20}?)\s*[:：]\s*(?P<value>\S.*?)\s*$")
_BODY_URL_VALUE_RE = re.compile(r"^(?:https?://|www\.)", re.IGNORECASE)
_BODY_HEADING_RE = re.compile(r"^={2,}\s*(?P<title>[^=].*?)\s*={2,}$")


def _label_tokens(label: str) -> set[str]:
    """字段标签比对用的分词：NFKC、去空白与「の」、按 / ・ 、 切开。

    「身長 / 体重」与正文的「身長」、「ブラサイズ」与「ブラのサイズ」要能对上，
    否则同一个字段会在两段里各写一遍（实测亜紗美词条的「プロフィール」节）。
    """
    folded = unicodedata.normalize("NFKC", label).replace("の", "").casefold()
    folded = re.sub(r"\s+", "", folded)
    return {token for token in re.split(r"[/・、,，]", folded) if token}


def _known_label_tokens(profile_lines: Sequence[str]) -> set[str]:
    known: set[str] = set()
    for line in profile_lines:
        label, sep, _value = line.partition(": ")
        if sep:
            known |= _label_tokens(label)
    return known


def _split_profile_fields(overview: str, profile_lines: Sequence[str]) -> tuple[str, list[str]]:
    """把正文里的「标签: 值」行归位到「个人资料」段，返回（剩余正文，补进资料段的字段）。

    部分词条（实测亜紗美）在正文里另有一节「プロフィール」，用列表把信息框的
    生年月日 / 出身地 / 身長 / スリーサイズ 再列一遍，数值还可能不一致；而「趣味 /
    特技 / 靴のサイズ」这类信息框没有的字段又值得保留。处理口径（用户 2026-11-08）：

    - 标签与「个人资料」段重复 → 该行删掉，不留两份口径不一的数值；
    - 标签是新的 → 该行移进「个人资料」段末，正文不再重复；
    - 字段行占该节非空行一半以上（资料列表型章节）→ 整节丢弃，连标题与「本数据
      出自某年事务所资料」这类说明句一起，避免留一个只有空话的段标题。

    导语（第一个标题之前）不动：它是一段连贯的叙述，不是字段列表。
    """
    known = _known_label_tokens(profile_lines)
    sections: list[tuple[str | None, list[str]]] = [(None, [])]
    for line in overview.split("\n"):
        if _BODY_HEADING_RE.match(line.strip()):
            sections.append((line.strip(), []))
        else:
            sections[-1][1].append(line)

    extras: list[str] = []
    extra_keys: set[str] = set()
    kept: list[tuple[str | None, list[str]]] = []
    for title, body_lines in sections:
        if title is None:
            kept.append((None, _trim_body_lines(body_lines)))
            continue
        non_empty = sum(1 for line in body_lines if line.strip())
        fields = 0
        remaining: list[str] = []
        for line in body_lines:
            match = _BODY_FIELD_RE.match(line)
            if not match or _BODY_URL_VALUE_RE.match(match.group("value")):
                remaining.append(line)
                continue
            keys = _label_tokens(match.group("label"))
            if not keys:
                remaining.append(line)
                continue
            fields += 1
            if keys & known:
                continue
            extra_key = "|".join(sorted(keys))
            if extra_key not in extra_keys:
                extra_keys.add(extra_key)
                extras.append(line.strip())
        if fields and fields * 2 >= non_empty:
            continue
        kept.append((title, _trim_body_lines(remaining)))

    parts: list[str] = []
    for title, body_lines in kept:
        body = "\n".join(body_lines).strip()
        if title is None:
            if body:
                parts.append(body)
            continue
        if not body:
            continue
        parts.append(f"{title}\n{body}")
    return "\n\n".join(parts), extras


def _trim_body_lines(lines: list[str]) -> list[str]:
    """删行后收拢空白：连续空行压成一个，首尾空行去掉，行尾空白不留。"""
    out: list[str] = []
    for line in lines:
        text = line.rstrip()
        if not text:
            if out and out[-1]:
                out.append("")
            continue
        out.append(text)
    while out and not out[-1]:
        out.pop()
    return out


def _split_lead(overview: str) -> tuple[str, str]:
    """把正文拆成（导语, 其余）：导语是第一个段标题之前的部分。

    导语是「谁」的一句话概括，放在最上面才读得顺（用户 2026-11-09）；没有段标题时
    整段都算导语，其余为空串。
    """
    lines = overview.split("\n")
    for index, line in enumerate(lines):
        if _BODY_HEADING_RE.match(line.strip()):
            return "\n".join(lines[:index]).strip(), "\n".join(lines[index:]).strip()
    return overview.strip(), ""


def _external_link_lines(profile: WikiActorProfile) -> list[str]:
    """「外部链接」段的每行一条：Wikidata 给的外部 ID + 词条本身地址。

    与老实现（``tools/wiki.py`` 的 url_log）同序同格式；没有的 ID 直接跳过，
    一条都没有且没有词条地址时返回空列表（整段不写）。
    """
    lines: list[str] = []
    for key, label, template in _PROVIDER_LINKS:
        value = (profile.provider_ids or {}).get(key)
        if isinstance(value, str) and value:
            lines.append(f"{label}: {template.format(value)}")
    if profile.source_url:
        lines.append(f"Wikipedia: {profile.source_url}")
    return lines
