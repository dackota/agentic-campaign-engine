"""The brand logo, served from our own stack: an inline SVG data URI, so no preview or email
depends on a host that can be down or unset. White mark on the brand color."""

import base64

BRAND_LOGO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="80" viewBox="0 0 320 80">'
    '<rect width="320" height="80" fill="#0b5fff"/>'
    '<circle cx="40" cy="40" r="22" fill="#ffffff"/>'
    '<text x="76" y="50" font-family="Helvetica, Arial, sans-serif" font-size="24" '
    'font-weight="bold" fill="#ffffff">Agentic Campaign</text></svg>'
)
BRAND_LOGO_URL = "data:image/svg+xml;base64," + base64.b64encode(BRAND_LOGO_SVG.encode()).decode()
