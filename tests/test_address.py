"""The regex address reader: labelled addresses, PIN-anchored ones, and the noise it must skip."""

from app.extraction.address import describe_address, find_address


class TestLabelled:
    def test_a_one_line_labelled_address(self):
        text = "Aarav Mehta\nAddress: 12, Gandhi Street, T. Nagar, Chennai - 600017, Tamil Nadu\nEmail: a@b.com"

        address = find_address(text)

        assert address["pincode"] == "600017"
        assert address["state"] == "Tamil Nadu"
        assert address["raw"].startswith("12, Gandhi Street")

    def test_a_labelled_address_spanning_lines_stops_at_the_pin(self):
        text = "Address:\n12/4 Nehru Nagar\nCoimbatore 641001\nEmail: a@b.com\nPhone: 9876543210"

        address = find_address(text)

        assert address["raw"] == "12/4 Nehru Nagar, Coimbatore 641001"
        assert address["pincode"] == "641001"

    def test_a_qualified_label_is_stripped_and_a_hyphenated_pin_is_read(self):
        text = "Address for Communication: No:4 Selva Nagar, Kizh Padappai, Kanchipuram Dt-601301"

        address = find_address(text)

        assert address["raw"].startswith("No:4 Selva Nagar")
        assert address["pincode"] == "601301"

    def test_a_labelled_address_never_swallows_contact_lines(self):
        text = "Permanent Address: Flat 3B, Baner Road, Pune\na@b.com"

        assert find_address(text)["raw"] == "Flat 3B, Baner Road, Pune"


class TestPinAnchored:
    def test_the_lines_above_a_pin_join_when_they_read_as_an_address(self):
        text = (
            "Aarav Mehta\n"
            "Flat 3B, Lotus Apartments, Baner Road\n"
            "Pune, Maharashtra 411045\n"
            "+91 9876543210 | aarav@example.com"
        )

        address = find_address(text)

        assert address["raw"] == "Flat 3B, Lotus Apartments, Baner Road, Pune, Maharashtra 411045"
        assert address["state"] == "Maharashtra"
        assert address["pincode"] == "411045"

    def test_a_name_line_is_not_pulled_into_the_address(self):
        text = "Kabir Nair\nSector 15, Noida 201301"

        assert find_address(text)["raw"] == "Sector 15, Noida 201301"


class TestNothingToFind:
    def test_plain_prose_has_no_address(self):
        assert find_address("Software engineer with 3 years of Django experience.") is None

    def test_a_phone_number_is_not_a_pin(self):
        assert find_address("Phone: 9876543210\nMobile 600017 1234") is None

    def test_a_bare_six_digit_number_needs_an_address_cue(self):
        assert find_address("Processed 250000 records a day") is None

    def test_empty_text(self):
        assert find_address("") is None and find_address(None) is None


class TestDescribe:
    def test_state_spellings_are_canonicalised(self):
        assert describe_address("Madurai, tamilnadu 625001")["state"] == "Tamil Nadu"
        assert describe_address("Puducherry 605001")["state"] == "Puducherry"
        assert describe_address("Sector 9, Chandigarh")["state"] == "Chandigarh"

    def test_newlines_become_commas_and_whitespace_collapses(self):
        assert describe_address("12  Main Rd\nChennai   600001")["raw"] == "12 Main Rd, Chennai 600001"

    def test_no_pin_no_state(self):
        assert describe_address("somewhere") == {"raw": "somewhere", "pincode": None, "state": None}
