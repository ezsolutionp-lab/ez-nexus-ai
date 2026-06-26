"""
EZ-NEXUS AI — AI Agent
Provides call transcript summarization, urgency triage, sentiment analysis,
and action-item extraction. Works without an external LLM by applying robust
keyword/heuristic rules; optionally enhances results with OpenAI GPT when an
API key is configured.
"""

from __future__ import annotations

import os
import re
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)


# ── Keyword sets for heuristic analysis ────────────────────────────────────

_URGENT_KEYWORDS = {
    "urgent", "emergency", "immediately", "asap", "critical", "crisis",
    "broken", "not working", "shut down", "down", "failure", "fail",
    "deadline", "today", "right now", "fire", "help", "sos",
}

_POSITIVE_KEYWORDS = {
    "great", "excellent", "amazing", "happy", "pleased", "satisfied",
    "fantastic", "good", "wonderful", "love", "appreciate", "thank",
    "perfect", "awesome", "helpful", "impressed",
}

_NEGATIVE_KEYWORDS = {
    "unhappy", "frustrated", "angry", "annoyed", "terrible", "horrible",
    "worst", "bad", "disappointed", "disgusted", "upset", "complaint",
    "refund", "cancel", "waste", "useless", "hate", "never again",
}

_ACTION_PATTERNS: List[re.Pattern] = [
    re.compile(r"\bwill\s+(?:call|send|email|follow[- ]?up|schedule|book|check|update|fix|review)\b", re.I),
    re.compile(r"\bneeds?\s+to\s+\w+", re.I),
    re.compile(r"\bplease\s+\w+", re.I),
    re.compile(r"\bfollow[- ]?up\b", re.I),
    re.compile(r"\bschedule\s+(?:a|an)?\s*(?:meeting|call|appointment|demo)\b", re.I),
    re.compile(r"\bsend\s+(?:a|an|the)?\s*(?:email|proposal|quote|invoice|document|report)\b", re.I),
    re.compile(r"\bcall\s+(?:back|them|us|me)\b", re.I),
    re.compile(r"\bconfirm\s+\w+", re.I),
]


# ── Core analysis functions ─────────────────────────────────────────────────

def _triage(text: str) -> str:
    """Return 'urgent', 'normal', or 'low' based on keyword density."""
    lower = text.lower()
    tokens = set(re.findall(r"\b\w+\b", lower))
    urgent_hits = len(tokens & _URGENT_KEYWORDS)

    if urgent_hits >= 2 or any(p in lower for p in ("asap", "right now", "help me now")):
        return "urgent"
    if urgent_hits == 1:
        return "normal"
    return "low"


def _sentiment(text: str) -> str:
    """Return 'positive', 'neutral', or 'negative'."""
    lower = text.lower()
    tokens = set(re.findall(r"\b\w+\b", lower))
    pos = len(tokens & _POSITIVE_KEYWORDS)
    neg = len(tokens & _NEGATIVE_KEYWORDS)

    if neg > pos:
        return "negative"
    if pos > neg:
        return "positive"
    return "neutral"


def _extract_action_items(text: str) -> List[str]:
    """Extract sentences containing action-item signals."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    actions: List[str] = []
    for sentence in sentences:
        for pattern in _ACTION_PATTERNS:
            if pattern.search(sentence):
                cleaned = sentence.strip()
                if cleaned and cleaned not in actions:
                    actions.append(cleaned)
                break
    return actions[:10]  # Cap at 10


def _summarize_heuristic(transcript: str) -> str:
    """
    Build a human-readable summary from the transcript using sentence selection.
    Picks the first 2 and last 2 sentences, plus any sentence with action signals.
    """
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", transcript.strip()) if s.strip()]

    if not sentences:
        return "No transcript content to summarize."
    if len(sentences) <= 4:
        return " ".join(sentences)

    selected = []
    # Opening context
    selected.extend(sentences[:2])
    # Action-heavy sentences (middle)
    for s in sentences[2:-2]:
        for pat in _ACTION_PATTERNS:
            if pat.search(s) and s not in selected:
                selected.append(s)
                break
    # Closing context
    for s in sentences[-2:]:
        if s not in selected:
            selected.append(s)

    return " ".join(selected)


# ── Claude AI integration ──────────────────────────────────────────────────

def _try_claude_analysis(transcript: str) -> dict | None:
    """Attempt Claude-powered analysis. Returns dict or None on failure."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    try:
        import anthropic
        import json

        client = anthropic.Anthropic(api_key=api_key)

        prompt = (
            "Analyze the following call transcript and respond with ONLY a JSON object "
            "(no markdown, no extra text) containing exactly these keys:\n"
            '  "summary": one-paragraph plain-English summary,\n'
            '  "triage": one of "urgent" | "normal" | "low",\n'
            '  "action_items": array of action-item strings (max 10),\n'
            '  "sentiment": one of "positive" | "neutral" | "negative"\n\n'
            f"Transcript:\n\n{transcript[:8000]}"
        )

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        content = response.content[0].text.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\n?", "", content)
            content = re.sub(r"\n?```$", "", content.strip())

        data = json.loads(content)
        return {
            "summary": data.get("summary", ""),
            "triage": data.get("triage", "normal"),
            "action_items": data.get("action_items", []),
            "sentiment": data.get("sentiment", "neutral"),
        }
    except Exception as exc:
        logger.warning("Claude analysis failed, falling back: %s", exc)
        return None


# ── Optional OpenAI fallback ───────────────────────────────────────────────

def _try_openai_analysis(transcript: str) -> dict | None:
    """
    Attempt GPT-powered analysis.  Returns a dict with keys
    {summary, triage, action_items, sentiment} or None on failure.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        import openai  # optional dep — only imported if key is present
        client = openai.OpenAI(api_key=api_key)

        system_prompt = (
            "You are an AI assistant for EZ-NEXUS AI, a business operations platform. "
            "Analyze the provided call transcript and respond with ONLY a JSON object "
            "(no markdown) containing:\n"
            '  "summary": one-paragraph plain-English summary,\n'
            '  "triage": one of "urgent" | "normal" | "low",\n'
            '  "action_items": array of action-item strings,\n'
            '  "sentiment": one of "positive" | "neutral" | "negative"'
        )

        resp = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Transcript:\n\n{transcript[:6000]}"},
            ],
            temperature=0.2,
            max_tokens=500,
            response_format={"type": "json_object"},
        )

        import json
        data = json.loads(resp.choices[0].message.content)
        # Normalise / fill any missing keys
        return {
            "summary": data.get("summary", ""),
            "triage": data.get("triage", "normal"),
            "action_items": data.get("action_items", []),
            "sentiment": data.get("sentiment", "neutral"),
        }

    except Exception as exc:
        logger.warning("OpenAI analysis failed, falling back to heuristics: %s", exc)
        return None


# ── Public interface ────────────────────────────────────────────────────────

def analyze_transcript(transcript: str) -> dict:
    """
    Full analysis pipeline.  Returns dict with:
        summary (str), triage (str), action_items (list[str]), sentiment (str)

    Tries OpenAI first; falls back to heuristics when no API key is set or
    when the OpenAI call fails.
    """
    if not transcript or not transcript.strip():
        return {
            "summary": "Empty transcript provided.",
            "triage": "low",
            "action_items": [],
            "sentiment": "neutral",
        }

    # Try Claude first
    claude_result = _try_claude_analysis(transcript)
    if claude_result:
        logger.info("Transcript analysed with Claude AI")
        return claude_result

    # Try OpenAI fallback
    openai_result = _try_openai_analysis(transcript)
    if openai_result:
        logger.info("Transcript analysed with OpenAI GPT")
        return openai_result

    # Heuristic fallback
    logger.info("Transcript analysed with heuristics (no API key)")
    return {
        "summary": _summarize_heuristic(transcript),
        "triage": _triage(transcript),
        "action_items": _extract_action_items(transcript),
        "sentiment": _sentiment(transcript),
    }


# ── Content Generation ──────────────────────────────────────────────────────

def generate_content(content_type: str, topic: str, brand_voice: str = "professional",
                     target_audience: str = "", keywords: str = "") -> dict:
    """Generate marketing content using Claude or heuristic fallback."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key:
        try:
            import anthropic, json as _json
            client = anthropic.Anthropic(api_key=api_key)
            type_map = {
                "instagram_post": "an Instagram post (caption only, max 150 words, engaging tone)",
                "facebook_post":  "a Facebook post (conversational, max 200 words, include a call to action)",
                "linkedin_post":  "a LinkedIn post (professional, max 250 words, with insights)",
                "blog_article":   "a blog article outline + first 300 words (SEO-friendly, with H2 headings)",
                "email_campaign": "an email campaign (subject line + body, professional, 200 words)",
                "video_script":   "a short video script (hook + 3 key points + CTA, max 200 words)",
            }
            fmt = type_map.get(content_type, "marketing content")
            hashtag_note = "Also provide 5-8 relevant hashtags in a JSON array field 'hashtags'." if "instagram" in content_type or "facebook" in content_type else ""
            subject_note = "Also provide a compelling email subject line in a field 'subject'." if content_type == "email_campaign" else ""
            prompt = (
                f"Generate {fmt} for this topic: '{topic}'.\n"
                f"Brand voice: {brand_voice}.\n"
                f"{'Target audience: ' + target_audience + '.' if target_audience else ''}\n"
                f"{'Keywords to include: ' + keywords + '.' if keywords else ''}\n"
                f"Respond with ONLY a JSON object with keys: 'content' (the main text), {hashtag_note} {subject_note}"
            )
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=1024,
                messages=[{"role": "user", "content": prompt}]
            )
            text = resp.content[0].text.strip()
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\n?", "", text)
                text = re.sub(r"\n?```$", "", text.strip())
            data = _json.loads(text)
            return {
                "content":  data.get("content", ""),
                "hashtags": data.get("hashtags", []),
                "subject":  data.get("subject"),
            }
        except Exception as e:
            logger.warning("Claude content generation failed: %s", e)

    # Heuristic fallback
    return _heuristic_content(content_type, topic, brand_voice, target_audience, keywords)


def _heuristic_content(content_type: str, topic: str, brand_voice: str,
                        target_audience: str, keywords: str) -> dict:
    audience = f" for {target_audience}" if target_audience else ""
    kw_list  = [k.strip() for k in keywords.split(",") if k.strip()]

    if content_type == "instagram_post":
        content = (
            f"✨ {topic.title()}\n\n"
            f"We're excited to share this with you{audience}! "
            f"Our team is dedicated to delivering excellence in everything we do.\n\n"
            f"{'Key highlights: ' + ', '.join(kw_list[:3]) + '.' if kw_list else ''}\n\n"
            f"Ready to learn more? Drop a comment or DM us today! 👇"
        )
        hashtags = [f"#{k.replace(' ','')}" for k in kw_list[:5]] + ["#business", "#growth", "#success"]
        return {"content": content.strip(), "hashtags": hashtags[:8], "subject": None}

    if content_type == "email_campaign":
        subject = f"Exciting News: {topic.title()}"
        content = (
            f"Hi there,\n\n"
            f"We wanted to reach out{audience} about {topic}.\n\n"
            f"{'Here are some key highlights: ' + ', '.join(kw_list) + '.' if kw_list else ''}\n\n"
            f"We'd love to connect and discuss how we can help you achieve your goals.\n\n"
            f"Best regards,\nThe Team"
        )
        return {"content": content, "hashtags": [], "subject": subject}

    if content_type == "video_script":
        content = (
            f"[HOOK] Are you struggling with {topic}? Watch this!\n\n"
            f"[POINT 1] First, let's talk about why {topic} matters{audience}.\n\n"
            f"[POINT 2] Here's what most people get wrong — and how to fix it.\n\n"
            f"[POINT 3] Our proven approach: {', '.join(kw_list[:2]) if kw_list else 'smart strategy, real results'}.\n\n"
            f"[CTA] Like this video, subscribe, and drop your questions in the comments below!"
        )
        return {"content": content, "hashtags": [], "subject": None}

    # Generic fallback
    content = (
        f"{topic.title()}\n\n"
        f"We're proud to offer {audience.strip() if audience else 'our clients'} the best in class.\n\n"
        f"{'Key focus areas: ' + ', '.join(kw_list) + '.' if kw_list else ''}\n\n"
        f"Get in touch with us today to learn more."
    )
    return {"content": content, "hashtags": [], "subject": None}


# ── Website Builder ─────────────────────────────────────────────────────────

_THEME_COLORS = {
    "blue":   {"primary": "#1B4FD8", "dark": "#0D1F3C", "accent": "#3B82F6"},
    "teal":   {"primary": "#0F766E", "dark": "#042f2e", "accent": "#14B8A6"},
    "purple": {"primary": "#7C3AED", "dark": "#1e0a4e", "accent": "#8B5CF6"},
    "dark":   {"primary": "#334155", "dark": "#0f172a", "accent": "#64748b"},
}


def build_website_html(business_name: str, industry: str, tagline: str = "",
                        description: str = "", services: str = "",
                        phone: str = "", email: str = "", address: str = "",
                        color_theme: str = "blue", **kwargs) -> str:
    """Generate a complete single-page HTML website."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            colors = _THEME_COLORS.get(color_theme, _THEME_COLORS["blue"])
            prompt = (
                f"Generate a complete, modern, single-page HTML website for this business.\n"
                f"Business: {business_name} | Industry: {industry}\n"
                f"Tagline: {tagline or 'Professional Services'}\n"
                f"Description: {description or 'We provide excellent services.'}\n"
                f"Services: {services or 'Contact us for our full list of services.'}\n"
                f"Phone: {phone} | Email: {email} | Address: {address}\n"
                f"Primary color: {colors['primary']} | Dark color: {colors['dark']}\n\n"
                "Requirements:\n"
                "- Full HTML5 document with embedded CSS (NO external dependencies except Google Fonts)\n"
                "- Mobile responsive with media queries\n"
                "- Sections: Hero, About, Services, Contact\n"
                "- Modern design with gradients, shadows, and smooth hover effects\n"
                "- Sticky navigation bar\n"
                "- Footer with contact info\n"
                "- Output ONLY the raw HTML, no markdown, no explanation"
            )
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=4096,
                messages=[{"role": "user", "content": prompt}]
            )
            html = resp.content[0].text.strip()
            if html.startswith("```"):
                html = re.sub(r"^```(?:html)?\n?", "", html)
                html = re.sub(r"\n?```$", "", html.strip())
            if html.startswith("<!DOCTYPE") or html.startswith("<html"):
                return html
        except Exception as e:
            logger.warning("Claude website generation failed: %s", e)

    return _heuristic_website(business_name, industry, tagline, description, services, phone, email, address, color_theme)


def _heuristic_website(business_name: str, industry: str, tagline: str,
                        description: str, services: str, phone: str,
                        email: str, address: str, color_theme: str) -> str:
    colors  = _THEME_COLORS.get(color_theme, _THEME_COLORS["blue"])
    primary = colors["primary"]
    dark    = colors["dark"]
    accent  = colors["accent"]
    svc_list = [s.strip() for s in services.split(",") if s.strip()] if services else ["Professional Consultation", "Expert Services", "Client Support"]
    svc_html = "".join(
        f'<div class="svc-card"><div class="svc-icon">✦</div><h3>{s}</h3><p>We provide top-quality {s.lower()} tailored to your needs.</p></div>'
        for s in svc_list[:6]
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{business_name}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Inter',sans-serif;color:#1e293b;background:#fff}}
nav{{position:sticky;top:0;background:{dark};padding:16px 40px;display:flex;justify-content:space-between;align-items:center;z-index:100;box-shadow:0 2px 20px rgba(0,0,0,.3)}}
.logo{{font-size:1.3rem;font-weight:800;color:#fff;letter-spacing:-.5px}}
.nav-links a{{color:rgba(255,255,255,.8);text-decoration:none;margin-left:28px;font-size:.9rem;font-weight:500;transition:color .2s}}
.nav-links a:hover{{color:#fff}}
.hero{{background:linear-gradient(135deg,{dark} 0%,{primary} 100%);padding:120px 40px;text-align:center;color:#fff}}
.hero h1{{font-size:3.5rem;font-weight:900;letter-spacing:-2px;margin-bottom:16px;line-height:1.1}}
.hero p{{font-size:1.2rem;opacity:.85;max-width:600px;margin:0 auto 36px}}
.hero-btns{{display:flex;gap:14px;justify-content:center;flex-wrap:wrap}}
.btn-white{{background:#fff;color:{primary};padding:14px 32px;border-radius:8px;font-weight:700;text-decoration:none;font-size:1rem;transition:all .2s;box-shadow:0 4px 16px rgba(0,0,0,.2)}}
.btn-white:hover{{transform:translateY(-2px);box-shadow:0 8px 24px rgba(0,0,0,.25)}}
.btn-outline{{border:2px solid rgba(255,255,255,.6);color:#fff;padding:14px 32px;border-radius:8px;font-weight:700;text-decoration:none;font-size:1rem;transition:all .2s}}
.btn-outline:hover{{background:rgba(255,255,255,.1)}}
.section{{padding:80px 40px;max-width:1100px;margin:0 auto}}
.section-title{{text-align:center;font-size:2.2rem;font-weight:800;color:{dark};margin-bottom:12px;letter-spacing:-.5px}}
.section-sub{{text-align:center;color:#64748b;font-size:1rem;margin-bottom:48px;max-width:500px;margin-left:auto;margin-right:auto}}
.about-grid{{display:grid;grid-template-columns:1fr 1fr;gap:40px;align-items:center}}
@media(max-width:700px){{.about-grid{{grid-template-columns:1fr}}}}
.about-img{{background:linear-gradient(135deg,{primary}22,{accent}33);border-radius:16px;height:280px;display:flex;align-items:center;justify-content:center;font-size:5rem}}
.about-text p{{color:#475569;line-height:1.8;font-size:1rem}}
.about-text h2{{font-size:1.8rem;font-weight:800;color:{dark};margin-bottom:16px}}
.services{{background:#f8faff;padding:80px 40px}}
.svc-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:20px;max-width:1100px;margin:0 auto}}
.svc-card{{background:#fff;border-radius:14px;padding:28px;box-shadow:0 2px 16px rgba(0,0,0,.06);border-top:4px solid {primary};transition:transform .2s,box-shadow .2s}}
.svc-card:hover{{transform:translateY(-4px);box-shadow:0 8px 32px rgba(0,0,0,.1)}}
.svc-icon{{font-size:1.8rem;margin-bottom:14px;color:{primary}}}
.svc-card h3{{font-size:1.1rem;font-weight:700;color:{dark};margin-bottom:8px}}
.svc-card p{{color:#64748b;font-size:.9rem;line-height:1.6}}
.contact{{background:{dark};color:#fff;padding:80px 40px;text-align:center}}
.contact h2{{font-size:2rem;font-weight:800;margin-bottom:12px}}
.contact p{{opacity:.8;margin-bottom:32px}}
.contact-cards{{display:flex;gap:20px;justify-content:center;flex-wrap:wrap;margin-bottom:40px}}
.contact-card{{background:rgba(255,255,255,.08);border-radius:12px;padding:20px 28px;min-width:200px}}
.contact-card .icon{{font-size:1.6rem;margin-bottom:8px}}
.contact-card .label{{font-size:.75rem;opacity:.6;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px}}
.contact-card .value{{font-weight:600;font-size:.95rem}}
footer{{background:#0f172a;color:rgba(255,255,255,.5);text-align:center;padding:20px;font-size:.85rem}}
</style>
</head>
<body>
<nav>
  <div class="logo">{business_name}</div>
  <div class="nav-links">
    <a href="#about">About</a><a href="#services">Services</a><a href="#contact">Contact</a>
  </div>
</nav>

<div class="hero">
  <h1>{business_name}</h1>
  <p>{tagline or f'Your trusted partner in {industry}'}</p>
  <div class="hero-btns">
    <a href="#contact" class="btn-white">Get Started</a>
    <a href="#services" class="btn-outline">Our Services</a>
  </div>
</div>

<div id="about" class="section">
  <div class="about-grid">
    <div class="about-img">🏢</div>
    <div class="about-text">
      <h2>About {business_name}</h2>
      <p>{description or f'We are a leading provider of {industry.lower()} services, committed to excellence and customer satisfaction. Our team of dedicated professionals works tirelessly to deliver results that exceed expectations.'}</p>
    </div>
  </div>
</div>

<div id="services" class="services">
  <div class="section-title">Our Services</div>
  <div class="section-sub">Everything you need, delivered with expertise</div>
  <div class="svc-grid">{svc_html}</div>
</div>

<div id="contact" class="contact">
  <h2>Get In Touch</h2>
  <p>We'd love to hear from you. Reach out today.</p>
  <div class="contact-cards">
    {'<div class="contact-card"><div class="icon">📞</div><div class="label">Phone</div><div class="value">' + phone + '</div></div>' if phone else ''}
    {'<div class="contact-card"><div class="icon">✉️</div><div class="label">Email</div><div class="value">' + email + '</div></div>' if email else ''}
    {'<div class="contact-card"><div class="icon">📍</div><div class="label">Address</div><div class="value">' + address + '</div></div>' if address else ''}
  </div>
</div>

<footer>© {business_name} · {industry} · All rights reserved</footer>
</body>
</html>"""


# ── E-Commerce / Product Hunting AI ─────────────────────────────────────────

_ECOM_CATEGORIES = {
    "home": ["Portable Mini Blender", "LED Smart Light Strip", "Bamboo Organizer Set", "Coffee Dripper Kit", "Aromatherapy Diffuser"],
    "electronics": ["Wireless Charging Pad", "USB-C Hub Dock", "Bluetooth Earbud Case", "Phone Ring Holder", "Mini Projector Clip"],
    "kitchen": ["Silicone Baking Mat Set", "Electric Spice Grinder", "Glass Meal Prep Containers", "Avocado Slicer Tool", "Oil Dispenser Bottle"],
    "fitness": ["Resistance Band Set", "Jump Rope Counter", "Yoga Block Foam", "Grip Strength Trainer", "Cooling Towel Sport"],
    "pet": ["Slow Feeder Bowl", "Interactive Laser Toy", "Travel Water Bottle Dog", "Grooming Glove", "Elevated Pet Bed"],
    "beauty": ["Gua Sha Stone Kit", "LED Face Mask", "Jade Roller Beauty", "Travel Makeup Organizer", "Nail Art Stamping Kit"],
    "outdoor": ["Compact Camping Lantern", "Foldable Water Bottle", "Hammock Straps Set", "Waterproof Dry Bag", "Multi-Tool Card"],
    "kids": ["Sensory Fidget Toy", "Magnetic Drawing Board", "Kids Gardening Set", "Foam Building Blocks", "DIY Craft Kit"],
}

_MARKETPLACE_FEES = {
    "Amazon": 15.0,
    "eBay": 12.5,
    "Shopify": 2.0,
    "Walmart": 15.0,
    "Etsy": 6.5,
    "TikTok Shop": 8.0,
}

_SUPPLIERS = [
    {"name": "QuickShip USA Wholesale", "country": "USA", "extra_cost": 0.40, "ship_days": 3},
    {"name": "ChinaTrade Direct", "country": "China", "extra_cost": -0.25, "ship_days": 14},
    {"name": "MexSource Partners", "country": "Mexico", "extra_cost": 0.15, "ship_days": 7},
    {"name": "CanadaStock Inc.", "country": "Canada", "extra_cost": 0.30, "ship_days": 5},
]


def _score_product(base_cost: float, selling_price: float) -> dict:
    import random
    margin = (selling_price - base_cost) / selling_price * 100 if selling_price else 0
    d = random.randint(62, 92)
    c = random.randint(40, 75)
    p = min(100, int(margin * 1.4))
    s = random.randint(70, 90)
    t = random.randint(60, 88)
    r = random.randint(55, 82)
    ai = int((d * 0.22) + (c * 0.1) + (p * 0.25) + (s * 0.18) + (t * 0.15) + (r * 0.10))
    return {"demand": d, "competition": c, "profit": p, "supplier": s, "trend": t, "risk": r, "ai": ai}


def _heuristic_hunt(category: str, marketplace: str, budget: float) -> list:
    import random
    cat_key = category.lower().split()[0] if category else "home"
    products = _ECOM_CATEGORIES.get(cat_key, _ECOM_CATEGORIES["home"])
    fee_pct = _MARKETPLACE_FEES.get(marketplace, 15.0) / 100

    results = []
    for p_name in products[:5]:
        cost = round(budget * random.uniform(0.28, 0.42), 2)
        sell = round(cost / (1 - fee_pct - 0.30), 2)
        profit = round(sell - cost - (sell * fee_pct) - round(sell * 0.08, 2), 2)
        monthly = random.randint(80, 420)
        scores = _score_product(cost, sell)
        supplier = random.choice(_SUPPLIERS)
        sup_cost = round(cost * supplier["extra_cost"] + cost, 2)
        rec_text = (
            f"Strong opportunity. AI Score {scores['ai']}/100. "
            f"Estimated {monthly} units/month. "
            f"Best supplier: {supplier['name']} ({supplier['country']}, ~{supplier['ship_days']} day ship)."
            if scores["ai"] >= 70
            else f"Moderate opportunity. Score {scores['ai']}/100. Requires deeper research before committing."
        )
        results.append({
            "product_name":            p_name,
            "category":                category,
            "marketplace":             marketplace,
            "demand_score":            scores["demand"],
            "competition_score":       scores["competition"],
            "profit_score":            scores["profit"],
            "supplier_score":          scores["supplier"],
            "trend_score":             scores["trend"],
            "risk_score":              scores["risk"],
            "ai_score":                scores["ai"],
            "ai_recommendation":       rec_text,
            "supplier_name":           supplier["name"],
            "supplier_country":        supplier["country"],
            "supplier_cost":           sup_cost,
            "selling_price":           sell,
            "estimated_profit":        max(0.0, profit),
            "estimated_monthly_sales": monthly,
        })
    return sorted(results, key=lambda x: x["ai_score"], reverse=True)


def hunt_products(category: str, marketplace: str, keywords: str = "", budget: float = 50.0) -> dict:
    try:
        import anthropic, os, json as _json
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ValueError("No API key")
        client = anthropic.Anthropic(api_key=api_key)
        prompt = (
            f"You are an expert ecommerce product hunting AI. Find 5 winning product opportunities.\n\n"
            f"Category: {category}\nMarketplace: {marketplace}\nKeywords: {keywords}\nBudget: ${budget}\n\n"
            f"Return ONLY a JSON object: {{\"products\": [{{\"product_name\": str, \"category\": str, \"marketplace\": str, "
            f"\"demand_score\": int, \"competition_score\": int, \"profit_score\": int, \"supplier_score\": int, "
            f"\"trend_score\": int, \"risk_score\": int, \"ai_score\": int, \"ai_recommendation\": str, "
            f"\"supplier_name\": str, \"supplier_country\": str, \"supplier_cost\": float, "
            f"\"selling_price\": float, \"estimated_profit\": float, \"estimated_monthly_sales\": int}}], \"summary\": str}}"
        )
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text
        import re
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            data = _json.loads(m.group())
            return data
        raise ValueError("No JSON")
    except Exception as e:
        logger.warning("Claude product hunt failed: %s — using heuristic", e)
        prods = _heuristic_hunt(category, marketplace, budget)
        top = prods[0]["product_name"] if prods else category
        return {
            "products": prods,
            "summary": f"AI found {len(prods)} product opportunities in {category} for {marketplace}. Top pick: {top}.",
        }


def build_listing(marketplace: str, product_name: str, features: str,
                  target_audience: str = "general consumers", keywords: str = "",
                  brand_voice: str = "professional") -> dict:
    try:
        import anthropic, os, json as _json
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ValueError("No API key")
        client = anthropic.Anthropic(api_key=api_key)
        prompt = (
            f"Create an optimized {marketplace} product listing.\n\n"
            f"Product: {product_name}\nFeatures: {features}\nTarget Audience: {target_audience}\n"
            f"Keywords: {keywords}\nBrand Voice: {brand_voice}\n\n"
            f"Return ONLY JSON: {{\"title\": str, \"bullets\": str, \"description\": str, \"keywords\": str, \"ad_headline\": str}}"
        )
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text
        import re
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            return _json.loads(m.group())
        raise ValueError("No JSON")
    except Exception as e:
        logger.warning("Claude listing builder failed: %s — using heuristic", e)
        return _heuristic_listing(marketplace, product_name, features, target_audience, keywords)


def _heuristic_listing(marketplace: str, product_name: str, features: str,
                       target_audience: str, keywords: str) -> dict:
    kw_list = [k.strip() for k in keywords.split(",") if k.strip()] or [product_name.split()[0].lower()]
    title = f"{product_name} — Premium Quality | {kw_list[0].title()} | Best for {target_audience.title()}"
    bullets = (
        f"• PREMIUM QUALITY: Made from high-quality materials for long-lasting durability\n"
        f"• PERFECT FOR {target_audience.upper()}: Designed to meet the needs of every customer\n"
        f"• EASY TO USE: Simple setup with no tools required — ready in minutes\n"
        f"• GREAT VALUE: Combines {features[:80] if features else 'top features'} at an unbeatable price\n"
        f"• 100% SATISFACTION: Backed by our customer satisfaction guarantee"
    )
    description = (
        f"Introducing the {product_name} — the ultimate choice for {target_audience}. "
        f"Featuring {features[:200] if features else 'premium quality and advanced design'}, "
        f"this product delivers exceptional performance. "
        f"Whether you're looking for everyday use or a special gift, the {product_name} is the perfect fit. "
        f"Order today with confidence."
    )
    ad_headline = f"#{product_name.replace(' ','').lower()} Best {product_name} for {target_audience}"
    return {
        "title":       title[:200],
        "bullets":     bullets,
        "description": description,
        "keywords":    ", ".join(kw_list[:10]),
        "ad_headline": ad_headline[:150],
    }
