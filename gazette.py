"""India's Motor Vehicles (Driving) Regulations 2017, quoted word for word in an Indian site's legal box: the speed
past a school or hospital where signs show it (reg. 16(5)) and, with a marked crossing, giving way at it (reg. 39(1)).
Written by code, never by a model, and never beside the page's own counts: a sign switches 16(5) on, a video cannot.
"""
import html

PDF = "https://keralapolice.gov.in/storage/orders/iaps/cir-15-2018.pdf"  # Kerala Police's copy of the Gazette, 16 pages
SOURCE = "Motor Vehicles (Driving) Regulations 2017, Gazette of India Extraordinary No. 525, 23 June 2017, G.S.R. 634(E)"
# (regulation, PDF page, its words verbatim): page 1 is Kerala Police's covering circular, the Gazette starts on page 2
SCHOOL_SPEED = ("16(5)", 10, "No driver shall drive at a speed exceeding twenty-five kilometre per hour or such lower "
                "speed as may be specified on the road signage while passing by a construction site or a school or a "
                "hospital, wherever indicated by signage, or on roads without footpaths and soft shoulders where "
                "pedestrians use a part of the carriageway to walk.")
GIVE_WAY = ("39(1)", 15, "While approaching an uncontrolled pedestrian crossing, the driver shall slowdown, stop and give "
            "way to pedestrians, users of invalid carriages and wheelchairs.")
SIGN_ONLY = "This rule applies where signs show it; we do not say any driver broke it."


def quote(reg, page, text):
    return (f'<blockquote>“{html.escape(text)}”<cite><a href="{PDF}#page={page}">Regulation {reg}, PDF page {page}'
            "</a></cite></blockquote>")


def rules(site):
    """The legal box's part for drivers: reg. 16(5) and SIGN_ONLY, then reg. 39(1) only when the site has a marked
    crossing ("zebra_m" not empty). Whether either applies at this gate is the authority's to say."""
    crossing = f"<h3>Giving way at a pedestrian crossing</h3>{quote(*GIVE_WAY)}" if site.get("zebra_m") else ""
    return (f"<h3>India's limit past a school or hospital where signs show it</h3>{quote(*SCHOOL_SPEED)}"
            f'<p class="note">{SIGN_ONLY}</p>{crossing}<p class="note">Source: {html.escape(SOURCE)} '
            f'(<a href="{PDF}">PDF</a>).</p>')
