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

# 简介上限：段落级拼装，放不下的那一段截到句末；剩余空间不足 _MIN_TAIL_CHARS 就不再续接。
_OVERVIEW_MAX_CHARS = 1500
_MIN_TAIL_CHARS = 30
_PARAGRAPH_SEP = "\n\n"
_SENTENCE_ENDS = "。．.！!？?…"

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
}

_PROFILE_BLOCK_TITLE = "===== 个人资料 ====="


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
                profile = await _build_profile(qid, entity, desc, entry_languages)
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
    身高/三围/罩杯等 Emby 没有对应字段的信息，按老实现拼进简介的「个人资料」段。
    """
    from ..config.enums import EmbyAction

    actions = list(emby_on or manager.config.emby_on)
    target_lang = "zh-hant" if EmbyAction.ACTOR_INFO_ZH_TW in actions else "zh-cn"

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

    profile_lines = _profile_lines(profile)
    overview = (profile.overview or "").strip()
    if profile_lines:
        block = _PROFILE_BLOCK_TITLE + "\n" + "\n".join(profile_lines)
        overview = f"{block}\n\n{overview}" if overview else block
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
    overview = _clip_blocks(_overview_blocks(html)) or None
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
    """
    blocks: list[str] = []
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
                blocks.append(text)
            continue
        if _has_ancestor(node.root, _LIST_TAGS):
            continue
        items = [text for text in (_clean_text(item) for item in node.xpath("./li")) if text]
        if items:
            blocks.append("\n".join(items))
    return blocks


def _heading_text(node: Selector) -> str:
    text = _EDIT_LINK_RE.sub("", "".join(node.xpath(".//text()").getall()))
    return re.sub(r"\s+", " ", text).strip()


def _is_section(title: str) -> bool:
    folded = zhconv.convert(title, "zh-cn").translate(_JA_HEADING_FOLD).lower()
    return any(keyword in folded for keyword in _SECTION_KEYWORDS)


def _clean_text(node: Selector) -> str:
    """节点文本：取真实文本（不按子节点补空格），去引用标记并收拢空白。"""
    return _clean_inline("".join(node.xpath(".//text()").getall()))


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


def _clip_blocks(blocks: list[str]) -> str:
    out = ""
    for block in blocks:
        sep = _PARAGRAPH_SEP if out else ""
        room = _OVERVIEW_MAX_CHARS - len(out) - len(sep)
        if len(block) <= room:
            out = f"{out}{sep}{block}"
            continue
        if room >= _MIN_TAIL_CHARS:
            out = f"{out}{sep}{_cut_at_sentence(block, room)}"
        break
    return out


def _cut_at_sentence(text: str, limit: int) -> str:
    """截到句末并为省略号留位，保证结果不超过 limit。"""
    head = text[: limit - 1]
    cut = max((head.rfind(end) for end in _SENTENCE_ENDS), default=-1)
    if cut >= 0:
        head = head[: cut + 1]
    return f"{head.rstrip()}…"


# 标签随词条语言一套：中文（简体）与日文。繁体渲染只出现在 zh-tw 变体，而中文词条固定取 zh-cn，因此不收。
_HEIGHT_LABELS: tuple[str, ...] = ("身長", "身高")
_SIZES_LABELS: tuple[str, ...] = ("スリーサイズ", "三围")
_CUP_LABELS: tuple[str, ...] = ("ブラサイズ", "罩杯")
# 信息框底部的「计量单位换算 / 英米単位系」折叠块渲染出同名的英制行（5英尺3英寸 / 32 - 23 - 34 英寸）。
# 单位不可省：只认公制，否则英寸会被当厘米写进身高与三围。
_METRIC = r"(?:cm|厘米)"
_CM = r"(\d{2,3}(?:\.\d+)?)"
_HEIGHT_RE = re.compile(rf"^{_CM}\s*{_METRIC}")
_SIZES_RE = re.compile(rf"^{_CM}\s*-\s*{_CM}\s*-\s*{_CM}\s*{_METRIC}")
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


def _parse_infobox(html: Selector) -> tuple[str | None, str | None, _Figure, list[str]]:
    """信息框的出身地、出生日期、身材与原始行；与词条语言无关，命中即取。"""
    birthplace = None
    birthday = None
    figure = _NO_FIGURE
    rows: list[str] = []
    seen_rows: set[str] = set()
    for row in html.css("table.infobox tr, .infobox tr"):
        label = (_extract_text(row, "string(./th)") or _extract_text(row, "string(.//th)") or "").strip()
        value = (_extract_text(row, "string(./td)") or _extract_text(row, "string(.//td)") or "").strip()
        if not label or not value:
            continue
        clean_value = _clean_inline(value)
        # 日文 infobox 会把 <span class="bday"> 的 ISO 日期再渲染一遍：\n        # 「(1971-01-19)1971年1月19日（55歳）」，去掉括号里的重复 ISO 日期。\n        clean_value = re.sub(r\"^\\s*[（(]\\d{4}-\\d{2}-\\d{2}[）)]\\s*\", \"\", clean_value)\n        line = f\"{label}: {clean_value}\"
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


def _profile_lines(profile: WikiActorProfile) -> list[str]:
    if profile.infobox:
        lines = list(profile.infobox)
        if profile.aliases and not any("别名" in line for line in lines):
            lines.append(f"别名: {'、'.join(profile.aliases)}")
        return lines
    lines: list[str] = []
    if profile.birthday:
        lines.append(f"生日: {profile.birthday}")
    if profile.birthplace:
        lines.append(f"出生地: {profile.birthplace}")
    if profile.height:
        lines.append(f"身高: {profile.height}cm")
    sizes = [value for value in (profile.bust, profile.waist, profile.hip) if value]
    if sizes:
        lines.append(f"三围: {'/'.join(str(value) for value in sizes)}")
    if profile.cup:
        lines.append(f"罩杯: {profile.cup}")
    if profile.aliases:
        lines.append(f"别名: {'、'.join(profile.aliases)}")
    return lines
