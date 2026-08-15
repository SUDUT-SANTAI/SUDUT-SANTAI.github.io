#!/usr/bin/env python3
"""
generate.py
Mengambil YouTube channel feed (Atom XML), lalu men-generate:
  - docs/index.html      -> halaman utama daftar video (SEO friendly)
  - docs/videos/<id>.html-> halaman detail per video (SEO friendly, JSON-LD VideoObject)
  - docs/feed.xml         -> salinan feed Atom asli (auto-update, bisa dipakai RSS reader)
  - docs/sitemap.xml       -> sitemap untuk semua halaman
  - docs/robots.txt        -> arahkan crawler ke sitemap

Jalankan lewat GitHub Actions secara terjadwal (lihat .github/workflows/update-feed.yml)
"""

import os
import re
import sys
import html
import datetime
import xml.etree.ElementTree as ET
import urllib.request

# ------------------------------------------------------------------
# KONFIGURASI
# ------------------------------------------------------------------
CHANNEL_ID = os.environ.get("YT_CHANNEL_ID", "UCX3eUzYV2LN5JmZPXULQM5Q")
FEED_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"

# GANTI dengan domain GitHub Pages kamu, misal:
# "https://username.github.io/nama-repo" atau custom domain "https://situskamu.com"
SITE_URL = os.environ.get("SITE_URL", "https://USERNAME.github.io/REPO").rstrip("/")

# Kode verifikasi Google Search Console (isi "content" dari tag <meta name="google-site-verification">)
# Dibiarkan otomatis ikut ter-generate di setiap build supaya tidak hilang saat index.html ditimpa ulang.
GOOGLE_SITE_VERIFICATION = os.environ.get("GOOGLE_SITE_VERIFICATION", "")

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "docs")
VIDEOS_DIR = os.path.join(OUT_DIR, "videos")

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}

# ------------------------------------------------------------------
# AMBIL FEED
# ------------------------------------------------------------------
def fetch_feed(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (feed-bot)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def parse_feed(xml_bytes: bytes):
    root = ET.fromstring(xml_bytes)
    channel_title = root.findtext("atom:title", default="YouTube Channel", namespaces=NS)
    channel_link = None
    for link in root.findall("atom:link", NS):
        if link.get("rel") == "alternate":
            channel_link = link.get("href")
    entries = []
    for entry in root.findall("atom:entry", NS):
        video_id = entry.findtext("yt:videoId", default="", namespaces=NS)
        title = entry.findtext("atom:title", default="", namespaces=NS)
        link_el = entry.find("atom:link", NS)
        link = link_el.get("href") if link_el is not None else f"https://www.youtube.com/watch?v={video_id}"
        published = entry.findtext("atom:published", default="", namespaces=NS)
        updated = entry.findtext("atom:updated", default="", namespaces=NS)
        author = entry.findtext("atom:author/atom:name", default=channel_title, namespaces=NS)

        media_group = entry.find("media:group", NS)
        description = ""
        thumbnail = ""
        if media_group is not None:
            description = media_group.findtext("media:description", default="", namespaces=NS) or ""
            thumb_el = media_group.find("media:thumbnail", NS)
            if thumb_el is not None:
                thumbnail = thumb_el.get("url", "")

        if not thumbnail and video_id:
            thumbnail = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

        entries.append({
            "video_id": video_id,
            "title": title.strip(),
            "link": link,
            "published": published,
            "updated": updated,
            "author": author,
            "description": description.strip(),
            "thumbnail": thumbnail,
        })
    return {
        "title": channel_title,
        "link": channel_link or f"https://www.youtube.com/channel/{CHANNEL_ID}",
        "entries": entries,
    }


# ------------------------------------------------------------------
# HELPER
# ------------------------------------------------------------------
def esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def slugify(video_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "", video_id) or "video"


def iso_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_now_rfc822() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")


def to_rfc822(iso_date: str) -> str:
    """Ubah tanggal ISO 8601 (dari feed YouTube) ke format RFC 822 (dibutuhkan RSS 2.0 / Pinterest)."""
    if not iso_date:
        return iso_now_rfc822()
    try:
        dt = datetime.datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
        return dt.strftime("%a, %d %b %Y %H:%M:%S %z")
    except ValueError:
        return iso_now_rfc822()


# ------------------------------------------------------------------
# GENERATE index.html
# ------------------------------------------------------------------
def build_index_html(feed: dict) -> str:
    title = esc(feed["title"])
    channel_link = esc(feed["link"])
    entries = feed["entries"]
    desc = f"Video terbaru dari {title}. Update otomatis dari YouTube."

    cards = []
    item_list_json = []
    for i, e in enumerate(entries, start=1):
        vid = slugify(e["video_id"])
        page_url = f"{SITE_URL}/videos/{vid}.html"
        cards.append(f"""
    <article class="video-card" itemscope itemtype="https://schema.org/VideoObject">
      <a href="videos/{vid}.html">
        <img src="{esc(e['thumbnail'])}" alt="{esc(e['title'])}" loading="lazy" width="320" height="180" itemprop="thumbnailUrl">
      </a>
      <h2 itemprop="name"><a href="videos/{vid}.html">{esc(e['title'])}</a></h2>
      <p class="meta">{esc(e['published'][:10])} &middot; {esc(e['author'])}</p>
      <p class="desc">{esc(e['description'][:160])}{"..." if len(e['description']) > 160 else ""}</p>
      <meta itemprop="uploadDate" content="{esc(e['published'])}">
      <meta itemprop="embedUrl" content="https://www.youtube.com/embed/{esc(e['video_id'])}">
    </article>""")
        item_list_json.append(
            f'{{"@type":"ListItem","position":{i},"url":"{page_url}"}}'
        )

    cards_html = "\n".join(cards)
    item_list_json_str = ",".join(item_list_json)

    gsc_tag = (
        f'<meta name="google-site-verification" content="{esc(GOOGLE_SITE_VERIFICATION)}">\n'
        if GOOGLE_SITE_VERIFICATION else ""
    )

    return f"""<!DOCTYPE html>
<html lang="id">
<head>
{gsc_tag}<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} - Video Terbaru</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{SITE_URL}/">
<link rel="alternate" type="application/atom+xml" title="{title} RSS Feed" href="{SITE_URL}/feed.xml">
<link rel="alternate" type="application/rss+xml" title="{title} Pinterest Feed" href="{SITE_URL}/pinterest.xml">
<link rel="sitemap" type="application/xml" href="{SITE_URL}/sitemap.xml">

<meta property="og:type" content="website">
<meta property="og:title" content="{title} - Video Terbaru">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{SITE_URL}/">
<meta name="twitter:card" content="summary_large_image">

<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "ItemList",
  "itemListElement": [{item_list_json_str}]
}}
</script>

<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; max-width: 1200px; margin: 0 auto; padding: 24px; line-height: 1.5; }}
  header {{ margin-bottom: 32px; }}
  header a {{ color: inherit; }}
  /* 4 kolom tetap di desktop, jumlah baris mengikuti banyaknya video (unlimited) */
  .grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; }}
  @media (max-width: 900px) {{ .grid {{ grid-template-columns: repeat(2, 1fr); }} }}
  @media (max-width: 560px) {{ .grid {{ grid-template-columns: 1fr; }} }}
  .video-card {{ border: 1px solid #ddd; border-radius: 8px; overflow: hidden; padding-bottom: 12px; }}
  .video-card img {{ width: 100%; height: auto; display: block; }}
  .video-card h2 {{ font-size: 1rem; margin: 8px 12px 4px; }}
  .video-card h2 a {{ color: inherit; text-decoration: none; }}
  .video-card .meta {{ font-size: .8rem; color: #666; margin: 0 12px; }}
  .video-card .desc {{ font-size: .85rem; margin: 6px 12px 0; color: #444; }}
  footer {{ margin-top: 40px; font-size: .8rem; color: #888; }}
</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <p><a href="{channel_link}" rel="noopener" target="_blank">Kunjungi channel YouTube</a> &middot; <a href="feed.xml">Feed RSS/XML</a> &middot; <a href="pinterest.xml">Feed Pinterest</a> &middot; <a href="random.html">🔀 Video Acak</a></p>

  <!-- Tombol subscribe resmi YouTube: otomatis ambil nama channel & jumlah subscriber langsung dari YouTube -->
  <div class="g-ytsubscribe" data-channelid="{CHANNEL_ID}" data-layout="full" data-count="default"></div>
</header>

<main class="grid">
{cards_html}
</main>

<footer>
  <p>Halaman ini dibuat otomatis dari YouTube RSS feed dan diperbarui secara berkala. Terakhir update: {iso_now()}</p>
</footer>

<script src="https://apis.google.com/js/platform.js"></script>
</body>
</html>
"""


# ------------------------------------------------------------------
# GENERATE halaman detail video
# ------------------------------------------------------------------
def build_video_html(e: dict, channel_title: str) -> str:
    vid = esc(e["video_id"])
    title = esc(e["title"])
    desc = esc(e["description"][:300])
    page_url = f"{SITE_URL}/videos/{slugify(e['video_id'])}.html"

    return f"""<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} - {esc(channel_title)}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{page_url}">

<meta property="og:type" content="video.other">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:image" content="{esc(e['thumbnail'])}">
<meta property="og:url" content="{page_url}">
<meta name="twitter:card" content="player">

<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "VideoObject",
  "name": {title!r},
  "description": {desc!r},
  "thumbnailUrl": "{esc(e['thumbnail'])}",
  "uploadDate": "{esc(e['published'])}",
  "embedUrl": "https://www.youtube.com/embed/{vid}",
  "contentUrl": "{esc(e['link'])}"
}}
</script>

<style>
  body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; max-width: 800px; margin: 0 auto; padding: 24px; line-height: 1.6; }}
  .video-wrap {{ position: relative; padding-bottom: 56.25%; height: 0; overflow: hidden; margin-bottom: 16px; }}
  .video-wrap iframe {{ position: absolute; top: 0; left: 0; width: 100%; height: 100%; border: 0; }}
  a.back {{ display: inline-block; margin-top: 24px; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="video-wrap">
  <iframe src="https://www.youtube.com/embed/{vid}" title="{title}" loading="lazy" allowfullscreen></iframe>
</div>
<p>{desc}</p>
<p><a href="{esc(e['link'])}" target="_blank" rel="noopener">Tonton di YouTube</a></p>
<a class="back" href="../index.html">&larr; Kembali ke semua video</a>
</body>
</html>
"""


# ------------------------------------------------------------------
# GENERATE random.html
# Halaman ini otomatis memilih 1 video acak dari feed lalu redirect ke sana.
# Dipakai untuk link "Video Acak" / tombol shuffle.
# ------------------------------------------------------------------
def build_random_html(feed: dict) -> str:
    title = esc(feed["title"])
    entries = [e for e in feed["entries"] if e["video_id"]]

    urls = [f"videos/{slugify(e['video_id'])}.html" for e in entries]
    urls_json = "[" + ",".join(f'"{u}"' for u in urls) + "]"

    if urls:
        redirect_script = f"""
    var pages = {urls_json};
    var pick = pages[Math.floor(Math.random() * pages.length)];
    window.location.replace(pick);
"""
        fallback_html = '<p>Mengalihkan ke video acak... Kalau tidak otomatis pindah, <a id="fallback-link" href="index.html">klik di sini</a>.</p>'
    else:
        redirect_script = ""
        fallback_html = '<p>Belum ada video tersedia. <a href="index.html">Lihat semua video</a>.</p>'

    return f"""<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Video Acak - {title}</title>
<meta name="robots" content="noindex, follow">
<link rel="canonical" href="{SITE_URL}/random.html">
<style>
  body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; max-width: 600px; margin: 80px auto; padding: 24px; text-align: center; line-height: 1.6; }}
</style>
<script>{redirect_script}</script>
</head>
<body>
<h1>Video Acak</h1>
{fallback_html}
<p><a href="index.html">&larr; Kembali ke semua video</a></p>
</body>
</html>
"""


# ------------------------------------------------------------------
# GENERATE pinterest.xml (RSS 2.0 + enclosure gambar)
# Format ini yang dibaca fitur Pinterest "Bulk-create Pins from RSS feed":
# Settings -> Bulk create pins -> Connect RSS feed
# ------------------------------------------------------------------
def build_pinterest_rss(feed: dict) -> str:
    title = esc(feed["title"])
    link = esc(feed["link"])
    now = iso_now_rfc822()

    items = []
    for e in feed["entries"]:
        if not e["video_id"]:
            continue
        vid = slugify(e["video_id"])
        page_url = f"{SITE_URL}/videos/{vid}.html"
        pub_date = to_rfc822(e["published"])
        desc = esc(e["description"][:500]) or esc(e["title"])
        items.append(f"""  <item>
    <title>{esc(e['title'])}</title>
    <link>{page_url}</link>
    <guid isPermaLink="true">{page_url}</guid>
    <pubDate>{pub_date}</pubDate>
    <description><![CDATA[{desc}]]></description>
    <enclosure url="{esc(e['thumbnail'])}" type="image/jpeg" />
    <media:content url="{esc(e['thumbnail'])}" medium="image" />
  </item>""")

    items_str = "\n".join(items)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
<channel>
  <title>{title}</title>
  <link>{link}</link>
  <description>Video terbaru dari {title}, auto-update untuk Pinterest.</description>
  <language>id</language>
  <lastBuildDate>{now}</lastBuildDate>
{items_str}
</channel>
</rss>
"""


# ------------------------------------------------------------------
# GENERATE sitemap.xml & robots.txt
# ------------------------------------------------------------------
def build_sitemap(entries) -> str:
    urls = [f"""  <url>
    <loc>{SITE_URL}/</loc>
    <changefreq>hourly</changefreq>
    <priority>1.0</priority>
  </url>"""]
    for e in entries:
        vid = slugify(e["video_id"])
        urls.append(f"""  <url>
    <loc>{SITE_URL}/videos/{vid}.html</loc>
    <lastmod>{esc(e['published'][:10])}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
  </url>""")
    urls_str = "\n".join(urls)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{urls_str}
</urlset>
"""


def build_robots() -> str:
    return f"""User-agent: *
Allow: /

Sitemap: {SITE_URL}/sitemap.xml
"""


# ------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------
def main():
    print(f"Mengambil feed: {FEED_URL}")
    try:
        xml_bytes = fetch_feed(FEED_URL)
    except Exception as exc:
        print(f"Gagal mengambil feed: {exc}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(VIDEOS_DIR, exist_ok=True)

    # 1. Simpan salinan feed XML asli (auto-update)
    with open(os.path.join(OUT_DIR, "feed.xml"), "wb") as f:
        f.write(xml_bytes)

    feed = parse_feed(xml_bytes)
    print(f"Channel: {feed['title']} - {len(feed['entries'])} video ditemukan")

    # 2. index.html
    with open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(build_index_html(feed))

    # 3. halaman per video
    for e in feed["entries"]:
        if not e["video_id"]:
            continue
        vid = slugify(e["video_id"])
        with open(os.path.join(VIDEOS_DIR, f"{vid}.html"), "w", encoding="utf-8") as f:
            f.write(build_video_html(e, feed["title"]))

    # 4. sitemap.xml & robots.txt
    with open(os.path.join(OUT_DIR, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write(build_sitemap(feed["entries"]))
    with open(os.path.join(OUT_DIR, "robots.txt"), "w", encoding="utf-8") as f:
        f.write(build_robots())

    # 5. pinterest.xml (RSS 2.0 khusus untuk fitur Bulk-create Pins Pinterest)
    with open(os.path.join(OUT_DIR, "pinterest.xml"), "w", encoding="utf-8") as f:
        f.write(build_pinterest_rss(feed))

    # 6. random.html (redirect otomatis ke 1 video acak)
    with open(os.path.join(OUT_DIR, "random.html"), "w", encoding="utf-8") as f:
        f.write(build_random_html(feed))

    # 7. file kosong .nojekyll agar GitHub Pages tidak memproses lewat Jekyll
    open(os.path.join(OUT_DIR, ".nojekyll"), "a").close()

    print("Selesai. File dibuat di folder docs/")


if __name__ == "__main__":
    main()
