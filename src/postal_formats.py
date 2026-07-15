"""Best-effort postal-code normalization to each country's canonical format.

AccuWeather's postal-code search is country-format-sensitive: for many countries a
code only resolves when written in its national canonical form. A Czech ``110 00``
(with the space) resolves, but the bare ``11000`` returns "No location found".
We normalize the user's free-text ``postal_query`` to the country's canonical
format before calling ``search_postal_codes``, so BOTH ``11000`` and ``110 00``
resolve for CZ.

Format templates below are the ``postalCodeFormat`` column of the GeoNames
``countryInfo.txt`` dump (https://download.geonames.org/export/dump/countryInfo.txt).
GeoNames notation: ``#`` = a digit, ``@`` = a letter, and any other character is a
literal (here only a space or a dash). Only separator-bearing formats are listed —
codes without a separator (e.g. US ``#####``, DE ``#####``) already resolve as
typed and pass through unchanged.

Scope note: we cover formats whose only literals are the separator (space / dash),
where reinsertion is unambiguous. GB and the UK-format crown dependencies use a
variable-length alphanumeric postcode, so they are handled by a dedicated rule
(the inward code is always the final 3 characters) rather than a fixed template.
"""

from typing import overload

# ISO-3166 alpha-2 -> canonical postal template (GeoNames postalCodeFormat).
# `#` = digit, `@` = letter; the literal space / dash marks where the separator
# is reinserted. Grouped by separator for readability.
POSTAL_FORMATS: dict[str, str] = {
    # --- space-separated national formats ---
    "CZ": "### ##",  # Czechia      e.g. 110 00
    "SK": "### ##",  # Slovakia     e.g. 811 01
    "SE": "### ##",  # Sweden       e.g. 113 51
    "NL": "#### @@",  # Netherlands  e.g. 1011 AC
    "CA": "@#@ #@#",  # Canada       e.g. K1A 0B1
    "MT": "@@@ ####",  # Malta        e.g. VLT 1117
    "AZ": "AZ ####",  # Azerbaijan   e.g. AZ 1000
    "BM": "@@ ##",  # Bermuda      e.g. CR 01
    # --- dash-separated national formats ---
    "PL": "##-###",  # Poland       e.g. 00-950
    "PT": "####-###",  # Portugal     e.g. 1000-260
    "JP": "###-####",  # Japan        e.g. 100-0001
    "BR": "#####-###",  # Brazil       e.g. 01310-100
    "NI": "###-###-#",  # Nicaragua
    "LT": "LT-#####",  # Lithuania    e.g. LT-01100
    "LV": "LV-####",  # Latvia       e.g. LV-1010
    "LU": "L-####",  # Luxembourg   e.g. L-1009
    "MD": "MD-####",  # Moldova      e.g. MD-2001
    "AI": "AI-####",  # Anguilla     e.g. AI-2640
    "PR": "#####-####",  # Puerto Rico  (US-style ZIP+4)
    "VI": "#####-####",  # US Virgin Islands
    "MH": "#####-####",  # Marshall Islands
}

# GB and the UK-format crown dependencies (GeoNames lists the multi-alternative
# `@# #@@|@## #@@|...`). Rather than match one of the seven alternatives, we rely
# on the invariant that a UK postcode's inward code is always the last 3 chars.
_UK_FORMAT_COUNTRIES: frozenset[str] = frozenset({"GB", "GG", "IM", "JE"})

_SEPARATORS: frozenset[str] = frozenset({" ", "-"})


def _strip_separators(text: str) -> str:
    """Collapse to the bare alphanumeric token (drop spaces and dashes)."""
    return text.replace(" ", "").replace("-", "")


def _apply_template(template: str, token: str) -> str:
    """Reinsert separators into ``token`` at the positions marked by ``template``.

    Caller guarantees ``len(token)`` equals the count of non-separator template
    characters, so consuming one token char per placeholder never overruns.
    """
    out: list[str] = []
    idx = 0
    for ch in template:
        if ch in _SEPARATORS:
            out.append(ch)
        else:
            out.append(token[idx])
            idx += 1
    return "".join(out)


@overload
def normalize_postal_code(country_code: str | None, raw: str) -> str: ...
@overload
def normalize_postal_code(country_code: str | None, raw: None) -> None: ...
def normalize_postal_code(country_code: str | None, raw: str | None) -> str | None:
    """Normalize a postal code to its country's canonical (separator-bearing) form.

    Pure and best-effort: it NEVER raises and NEVER turns a valid input invalid.
    When it cannot confidently reformat, it returns the input essentially unchanged.

    - ``None`` / empty / whitespace-only ``raw`` -> returned unchanged.
    - No ``country_code`` -> passthrough (returned unchanged).
    - Known template + matching length -> uppercased, separators reinserted per
      template (CZ ``### ##`` + ``11000`` -> ``110 00``; ``110 00`` stays ``110 00``).
    - GB / UK-format -> single space so the last 3 chars are the inward code
      (``SW1A1AA`` -> ``SW1A 1AA``).
    - Unknown country, or a length that does not fit the template -> best-effort
      passthrough (never invalidated).
    """
    if raw is None:
        return raw
    trimmed = raw.strip()
    if not trimmed:
        return raw
    if not country_code or not country_code.strip():
        return raw

    cc = country_code.strip().upper()
    text = trimmed.upper()
    token = _strip_separators(text)

    if cc in _UK_FORMAT_COUNTRIES:
        # Inward code is always the trailing 3 chars; anything shorter can't be split.
        if len(token) < 4:
            return text
        return f"{token[:-3]} {token[-3:]}"

    template = POSTAL_FORMATS.get(cc)
    if template is None:
        return raw  # unknown country: leave the user's input untouched

    placeholders = sum(1 for ch in template if ch not in _SEPARATORS)
    if len(token) != placeholders:
        # Length doesn't fit the canonical template — don't risk mangling it.
        return raw
    return _apply_template(template, token)
