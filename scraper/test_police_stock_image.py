"""Police-involved stories take the stock police photo, not the beige card.

Editor, 8 Nov 2026: "use the generic police image for stories like this",
about "Woman in her 50s dies at Tesco in Rochdale after emergency services
called" (filed as news, no police word in the headline, GMP in the copy).
"""
from pathlib import Path
import tempfile

from PIL import Image

import image_hierarchy as ih


def library(with_police=True):
    root = Path(tempfile.mkdtemp())
    folder = root / "assets/img/cards"
    folder.mkdir(parents=True)
    if with_police:
        Image.new("RGB", (1200, 675), "navy").save(folder / "police.jpg", quality=90)
    return root


TESCO = {
    "slug": "woman-dies-after-emergency-services-called-to-tesco-in-rochdale",
    "title": "Woman in her 50s dies at Tesco in Rochdale after emergency services called",
    "category": "news", "area": "rochdale", "police_matter": False,
    "content_html": "<p>Greater Manchester Police (GMP) received a report concerning the welfare of a woman.</p>",
    "image_url": "assets/img/cards/4217e0f83d9e-place-generated-card.jpg", "image_status": "place-generated-card",
}


def test_tesco_death_story_gets_police_image():
    root = library()
    story = dict(TESCO)
    assert ih.choose_image(story, root, allow_network=False) == "police-image"
    assert story["image_url"] == "assets/img/cards/police.jpg"
    assert story["image_status"] == "standard-police-image"
    assert story["image_alt"].startswith("Stock image: police")
    # Still upgradeable to GMP's own release photo by the granted-source step.
    from repair_generated_article_images import is_generated_or_placeholder
    assert is_generated_or_placeholder(story)
    # Readers see it is a stock image.
    assert ih.visible_image_note(story).startswith("Stock image:")


def test_crime_category_and_police_headline():
    root = library()
    crime = {"slug": "theft", "title": "Man charged after theft", "category": "crime", "area": "heywood"}
    headline = {"slug": "cmd", "title": "New transport policing command to cover Rochdale buses",
                "category": "transport", "area": "rochdale"}
    assert ih.choose_image(crime, root, allow_network=False) == "police-image"
    assert ih.choose_image(headline, root, allow_network=False) == "police-image"


def test_passing_police_mention_on_ordinary_story_is_untouched():
    root = library()
    story = {"slug": "fireworks", "title": "Fireworks distributor with Rochdale premises fined £40,000",
             "category": "news", "area": "rochdale",
             "content_html": "<p>The fire service worked with police and trading standards.</p>"}
    assert not ih.police_photo_story(story)
    assert ih.choose_image(story, root, allow_network=False) == "place-card"


def test_sponsored_never_and_missing_file_falls_back():
    root = library()
    sponsored = dict(TESCO, slug="s", title="Sponsored: police-approved locks", sponsored=True)
    assert not ih.police_photo_story(sponsored)
    bare = library(with_police=False)
    assert ih.choose_image(dict(TESCO), bare, allow_network=False) == "place-card"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("Police stock image checks passed.")
