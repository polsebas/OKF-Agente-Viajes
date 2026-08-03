"""Normaliza fixtures/viaje-china a frontmatter OKF (type/timestamp/tags).

Idempotente: se puede re-correr. Preserva el body; reescribe metadata.
Tambien crea _meta/tags.md y concepts type=day para get_day_itinerary.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path

import frontmatter

ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "viaje-china"

TYPE_MAP = {
    "dashboard": "dashboard",
    "ciudad": "city",
    "guia": "guide",
    "plan": "plan",
    "catalogo": "catalog",
    "lectura": "reading",
}

# concept_id (stem) -> (type, title, timestamp ISO date, tags, extra)
CITY_SPECS: dict[str, dict] = {
    "03 - Beijing": {
        "type": "city",
        "title": "Beijing",
        "timestamp": "2026-09-07",
        "tags": ["china", "beijing", "viaje2026"],
        "extra": {
            "ciudad": "Beijing",
            "pais": "China",
            "fechas": "7-10 de septiembre de 2026",
            "hotel": "Beijing Peace Hotel",
            "viaje": "China 2026",
        },
    },
    "04 - Datong": {
        "type": "city",
        "title": "Datong",
        "timestamp": "2026-09-10",
        "tags": ["china", "datong", "viaje2026"],
        "extra": {
            "ciudad": "Datong",
            "pais": "China",
            "fechas": "10-13 de septiembre de 2026",
            "hotel": "Datong Garden Hotel",
            "viaje": "China 2026",
        },
    },
    "05 - Xian": {
        "type": "city",
        "title": "Xian",
        "timestamp": "2026-09-13",
        "tags": ["china", "xian", "viaje2026"],
        "extra": {
            "ciudad": "Xian",
            "pais": "China",
            "fechas": "13-15 de septiembre de 2026",
            "hotel": "Hilton Garden Inn Xian Bell Tower",
            "viaje": "China 2026",
        },
    },
    "06 - Chengdu": {
        "type": "city",
        "title": "Chengdu",
        "timestamp": "2026-09-15",
        "tags": ["china", "chengdu", "viaje2026"],
        "extra": {
            "ciudad": "Chengdu",
            "pais": "China",
            "fechas": "15-17 de septiembre de 2026",
            "hotel": "Tibet Hotel Chengdu",
            "viaje": "China 2026",
        },
    },
    "07 - Chongqing": {
        "type": "city",
        "title": "Chongqing",
        "timestamp": "2026-09-17",
        "tags": ["china", "chongqing", "viaje2026"],
        "extra": {
            "ciudad": "Chongqing",
            "pais": "China",
            "fechas": "17-19 de septiembre de 2026",
            "hotel": "TRYP BY WYNDHAM CHONGQING DOWNTOWN",
            "viaje": "China 2026",
        },
    },
    "08 - Zhangjiajie": {
        "type": "city",
        "title": "Zhangjiajie",
        "timestamp": "2026-09-19",
        "tags": ["china", "zhangjiajie", "viaje2026"],
        "extra": {
            "ciudad": "Zhangjiajie",
            "pais": "China",
            "fechas": "19-21 de septiembre de 2026",
            "hotel": "Howard Johnson Neodalle Resort Zhangjiajie",
            "viaje": "China 2026",
        },
    },
    "09 - Furong": {
        "type": "city",
        "title": "Furong",
        "timestamp": "2026-09-21",
        "tags": ["china", "furong", "viaje2026"],
        "extra": {
            "ciudad": "Furong",
            "pais": "China",
            "fechas": "21-22 de septiembre de 2026",
            "hotel": "Tusi Xuanfu (Furong Town Waterfall Store)",
            "viaje": "China 2026",
        },
    },
    "10 - Fenghuang": {
        "type": "city",
        "title": "Fenghuang",
        "timestamp": "2026-09-22",
        "tags": ["china", "fenghuang", "viaje2026"],
        "extra": {
            "ciudad": "Fenghuang",
            "pais": "China",
            "fechas": "22-23 de septiembre de 2026",
            "hotel": "Sulv Lianhua Hotel",
            "viaje": "China 2026",
        },
    },
    "11 - Shanghai": {
        "type": "city",
        "title": "Shanghai",
        "timestamp": "2026-09-23",
        "tags": ["china", "shanghai", "viaje2026"],
        "extra": {
            "ciudad": "Shanghai",
            "pais": "China",
            "fechas": "23-26 de septiembre de 2026",
            "hotel": "Hengshan Garden Hotel",
            "viaje": "China 2026",
        },
    },
    "12 - Guilin": {
        "type": "city",
        "title": "Guilin",
        "timestamp": "2026-09-26",
        "tags": ["china", "guilin", "viaje2026"],
        "extra": {
            "ciudad": "Guilin",
            "pais": "China",
            "fechas": "26-28 de septiembre de 2026",
            "hotel": "Sheraton Guilin",
            "viaje": "China 2026",
        },
    },
    "13 - Hong Kong": {
        "type": "city",
        "title": "Hong Kong",
        "timestamp": "2026-09-28",
        "tags": ["china", "hong-kong", "viaje2026"],
        "extra": {
            "ciudad": "Hong Kong",
            "pais": "China",
            "fechas": "28 de septiembre - 1 de octubre de 2026",
            "hotel": "Park Hotel Hong Kong",
            "viaje": "China 2026",
        },
    },
}

# Dia calendario -> (city stem, day title)
DAY_ASSIGNMENTS: list[tuple[date, str, str]] = []


def _build_day_assignments() -> None:
    spans = [
        (date(2026, 9, 7), date(2026, 9, 10), "03 - Beijing", "Beijing"),
        (date(2026, 9, 10), date(2026, 9, 13), "04 - Datong", "Datong"),
        (date(2026, 9, 13), date(2026, 9, 15), "05 - Xian", "Xian"),
        (date(2026, 9, 15), date(2026, 9, 17), "06 - Chengdu", "Chengdu"),
        (date(2026, 9, 17), date(2026, 9, 19), "07 - Chongqing", "Chongqing"),
        (date(2026, 9, 19), date(2026, 9, 21), "08 - Zhangjiajie", "Zhangjiajie"),
        (date(2026, 9, 21), date(2026, 9, 22), "09 - Furong", "Furong"),
        (date(2026, 9, 22), date(2026, 9, 23), "10 - Fenghuang", "Fenghuang"),
        (date(2026, 9, 23), date(2026, 9, 26), "11 - Shanghai", "Shanghai"),
        (date(2026, 9, 26), date(2026, 9, 28), "12 - Guilin", "Guilin"),
        (date(2026, 9, 28), date(2026, 10, 2), "13 - Hong Kong", "Hong Kong"),
    ]
    DAY_ASSIGNMENTS.clear()
    day_num = 1
    for start, end, city_stem, city_name in spans:
        d = start
        while d < end:
            label = "Llegada a Beijing" if d == date(2026, 9, 7) else city_name
            DAY_ASSIGNMENTS.append((d, city_stem, f"Dia {day_num} - {label}"))
            d += timedelta(days=1)
            day_num += 1


_HASHTAG_RE = re.compile(r"(?m)^#[\w\-]+(?:\s+#[\w\-]+)*\s*$")
_INLINE_TAG_RE = re.compile(r"#([\w\-]+)")


def _extract_hashtags(body: str) -> list[str]:
    tags: list[str] = []
    for match in _INLINE_TAG_RE.finditer(body[:800]):
        tag = match.group(1).lower()
        if tag not in tags:
            tags.append(tag)
    return tags


def _write_post(path: Path, metadata: dict, body: str) -> None:
    post = frontmatter.Post(body, **metadata)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        frontmatter.dump(post, fh)


def _normalize_existing_file(path: Path) -> None:
    stem = path.stem
    # Skip day stubs and taxonomy written by this script on re-run content-wise ok
    if stem == "tags" and path.parent.name == "_meta":
        return
    if path.parent.name == "dias":
        return

    post = frontmatter.load(path)
    meta = dict(post.metadata)
    body = post.content

    if stem in CITY_SPECS:
        spec = CITY_SPECS[stem]
        tags = list(dict.fromkeys(spec["tags"] + _extract_hashtags(body)))
        # keep useful producer keys not already modeled
        new_meta = {
            "type": "city",
            "title": spec["title"],
            "tags": tags,
            "timestamp": datetime.fromisoformat(spec["timestamp"]).isoformat(),
            **spec["extra"],
        }
        _write_post(path, new_meta, body)
        print(f"city  {path.name}")
        return

    raw_tipo = (meta.get("type") or meta.get("tipo") or "").strip()
    mapped = TYPE_MAP.get(raw_tipo.lower(), "") if raw_tipo else ""

    if stem == "00 - Dashboard":
        mapped = "dashboard"
    elif stem.startswith("01 -") or stem.startswith("02 -"):
        mapped = "note"
    elif "Preparativos" in stem or "Checklists" in stem:
        mapped = "note"
    elif "Pagos" in stem or "Aplicaciones" in stem or "Compras" in stem:
        mapped = "guide"
    elif "Diario" in stem or "Después" in stem or "Curiosidades" in stem:
        mapped = "note"
    elif stem == "README":
        mapped = "note"
    elif not mapped:
        mapped = "note"

    tags = meta.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    tags = [str(t).lower() for t in tags]
    for t in _extract_hashtags(body):
        if t not in tags:
            tags.append(t)
    if "china" not in tags and stem != "README":
        tags.insert(0, "china")
    if "viaje2026" not in tags:
        tags.append("viaje2026")

    title = meta.get("title") or meta.get("titulo") or meta.get("ciudad") or stem
    new_meta = {"type": mapped, "title": title, "tags": tags, "viaje": meta.get("viaje", "China 2026")}
    # preserve selected extras
    for key in ("orden", "ciudad", "pais", "fechas", "hotel", "dias", "provincia", "zona", "aliases"):
        if key in meta:
            new_meta[key] = meta[key]
    # drop obsolete tipo
    _write_post(path, new_meta, body)
    print(f"{mapped:10} {path.name}")


def _write_taxonomy() -> None:
    body_lines = []
    cities = [
        ("china", [], ["beijing", "datong", "xian", "chengdu", "chongqing", "zhangjiajie", "furong", "fenghuang", "shanghai", "guilin", "hong-kong"]),
        ("viaje2026", ["viaje-2026", "china2026"], []),
        ("beijing", ["pekín", "pekin"], []),
        ("datong", [], []),
        ("xian", ["xi'an", "xi-an"], []),
        ("chengdu", [], []),
        ("chongqing", [], []),
        ("zhangjiajie", [], []),
        ("furong", [], []),
        ("fenghuang", [], []),
        ("shanghai", [], []),
        ("guilin", [], []),
        ("hong-kong", ["hongkong", "hk"], []),
        ("compras", ["shopping"], []),
        ("fotografia", ["foto", "dji", "dji-osmo"], []),
        ("gastronomia", ["comida"], []),
        ("dashboard", ["core"], []),
    ]
    for canonical, aliases, children in cities:
        body_lines.append(f"## {canonical}")
        body_lines.append(f"canonical: {canonical}")
        body_lines.append(f"aliases: [{', '.join(aliases)}]")
        body_lines.append(f"children: [{', '.join(children)}]")
        body_lines.append("")
    path = ROOT / "_meta" / "tags.md"
    _write_post(path, {"type": "tag-taxonomy", "title": "Taxonomia China 2026"}, "\n".join(body_lines))
    print(f"wrote {path.relative_to(ROOT)}")


def _write_index() -> None:
    links = [
        ("00 - Dashboard.md", "Dashboard"),
        ("03 - Beijing.md", "Beijing"),
        ("04 - Datong.md", "Datong"),
        ("05 - Xian.md", "Xian"),
        ("06 - Chengdu.md", "Chengdu"),
        ("07 - Chongqing.md", "Chongqing"),
        ("08 - Zhangjiajie.md", "Zhangjiajie"),
        ("09 - Furong.md", "Furong"),
        ("10 - Fenghuang.md", "Fenghuang"),
        ("11 - Shanghai.md", "Shanghai"),
        ("12 - Guilin.md", "Guilin"),
        ("13 - Hong Kong.md", "Hong Kong"),
        ("01 - Preparativos.md", "Preparativos"),
        ("15 - Pagos.md", "Pagos"),
        ("14 - Aplicaciones.md", "Aplicaciones"),
    ]
    body = ["# Viaje China 2026", "", "## Hub", ""]
    for href, label in links:
        body.append(f"- [{label}]({href})")
    body.append("")
    body.append("## Dias")
    body.append("")
    for d, city_stem, title in DAY_ASSIGNMENTS:
        day_file = f"dias/dia-{d.isoformat()}.md"
        body.append(f"- [{title}]({day_file}) → [{city_stem}]({city_stem}.md)")
    body.append("")
    _write_post(
        ROOT / "index.md",
        {
            "type": "note",
            "title": "Viaje China 2026",
            "tags": ["china", "viaje2026", "index"],
            "timestamp": "2026-09-07T00:00:00",
        },
        "\n".join(body),
    )
    print("wrote index.md")

    # Dashboard: OKF type + markdown links a archivos reales
    dash_body = """# Guia de Viaje China 2026

Centro de comando del vault. El itinerario corre del 7 de septiembre al 1 de octubre de 2026.

## Recorrido (ciudades)

- [Beijing](03 - Beijing.md) — llegada 7 sep 2026 (dias 1-3)
- [Datong](04 - Datong.md) (dias 4-6)
- [Xian](05 - Xian.md) (dias 7-8)
- [Chengdu](06 - Chengdu.md) (dias 9-10)
- [Chongqing](07 - Chongqing.md) (dias 11-12)
- [Zhangjiajie](08 - Zhangjiajie.md) (dias 13-14)
- [Furong](09 - Furong.md) (dia 15)
- [Fenghuang](10 - Fenghuang.md) (dia 16)
- [Shanghai](11 - Shanghai.md) (dias 17-19)
- [Guilin](12 - Guilin.md) (dias 20-21)
- [Hong Kong](13 - Hong Kong.md) (dias 22-25)

## Logistica

- [Preparativos](01 - Preparativos.md)
- [Pagos](15 - Pagos.md)
- [Aplicaciones](14 - Aplicaciones.md)
- [Indice OKF](index.md)
"""
    _write_post(
        ROOT / "00 - Dashboard.md",
        {
            "type": "dashboard",
            "title": "Dashboard China 2026",
            "tags": ["dashboard", "china", "viaje2026"],
            "timestamp": "2026-09-07T00:00:00",
            "aliases": ["Inicio", "Hub"],
        },
        dash_body,
    )
    print("rewrote 00 - Dashboard.md")


def _write_days() -> None:
    dias_dir = ROOT / "dias"
    dias_dir.mkdir(exist_ok=True)
    for d, city_stem, title in DAY_ASSIGNMENTS:
        city_tag = CITY_SPECS[city_stem]["tags"][1] if len(CITY_SPECS[city_stem]["tags"]) > 1 else "china"
        # relative link from dias/ to root file
        href = f"../{city_stem}.md"
        body = (
            f"Itinerario del {d.isoformat()}.\n\n"
            f"Detalle en [{CITY_SPECS[city_stem]['title']}]({href}).\n"
        )
        if d == date(2026, 9, 7):
            body = (
                "Llegada a Beijing (inicio del viaje).\n\n"
                f"Detalle en [Beijing]({href}).\n"
            )
        path = dias_dir / f"dia-{d.isoformat()}.md"
        _write_post(
            path,
            {
                "type": "day",
                "title": title,
                "tags": ["china", city_tag, "viaje2026"],
                "timestamp": f"{d.isoformat()}T00:00:00",
            },
            body,
        )
    print(f"wrote {len(DAY_ASSIGNMENTS)} day concepts in dias/")


def main() -> None:
    _build_day_assignments()
    for path in sorted(ROOT.glob("*.md")):
        _normalize_existing_file(path)
    _write_taxonomy()
    _write_days()
    _write_index()
    # remove broken double-extension index if present
    legacy = ROOT / "00 - Índice.md.md"
    if legacy.exists():
        legacy.unlink()
        print("removed 00 - Índice.md.md")


if __name__ == "__main__":
    main()
