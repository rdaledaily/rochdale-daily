from social_radar import classify_record, process_records


def test_membership_email_is_noise():
    assert classify_record({
        "sender": "Facebook Groups <groupupdates@facebookmail.com>",
        "subject": "Sarah, you're now a member of Rochdale's nosey gang",
        "snippet": "Your request to join Rochdale's nosey gang has been approved.",
    }) is None


def test_crash_is_high_priority_verification_lead():
    lead = classify_record({
        "sender": "Facebook Groups <groupupdates@facebookmail.com>",
        "subject": "New post in Rochdale Community",
        "snippet": "Anyone know what's happened on Bury Road in Rochdale? Police everywhere after a crash.",
        "source_context": "Rochdale Community",
        "received_at": "2026-08-16T12:10:00Z",
    })
    assert lead is not None
    assert "traffic" in lead.topics
    assert lead.status == "verify_now"
    assert lead.priority >= 80
    assert lead.verification_required is True


def test_bins_and_restaurant_events_are_kept_as_leads():
    result = process_records([
        {
            "sender": "groupupdates@facebookmail.com",
            "snippet": "Bins on Norden Road in Rochdale have not been collected again.",
            "source_context": "Norden Community",
        },
        {
            "sender": "groupupdates@facebookmail.com",
            "snippet": "La Piazza restaurant in Rochdale has live music tonight and a new menu offer.",
            "source_context": "Rochdale Food & Drink",
        },
    ])
    assert result["lead_count"] == 2
    statuses = {lead["status"] for lead in result["leads"]}
    assert "review" in statuses
    assert "event_candidate" in statuses


def test_identifiable_allegation_is_held_not_publishable():
    lead = classify_record({
        "sender": "groupupdates@facebookmail.com",
        "snippet": "Rochdale warning: this man is a thief and stole my parcel.",
        "source_context": "Rochdale Local Group",
    })
    assert lead is not None
    assert lead.legal_risk is True
    assert lead.status == "legal_hold"
    assert lead.verification_required is True


def test_similar_reports_cluster_and_raise_signal_count():
    result = process_records([
        {
            "sender": "groupupdates@facebookmail.com",
            "snippet": "Crash on Bury Road Rochdale, road closed and police are there.",
            "source_context": "Rochdale Community",
        },
        {
            "sender": "groupupdates@facebookmail.com",
            "snippet": "Bury Road Rochdale crash - road is closed, police on scene.",
            "source_context": "Rochdale Community",
        },
    ])
    assert result["lead_count"] == 1
    lead = result["leads"][0]
    assert lead["signals"] == 2
    assert lead["duplicate_count"] == 1
    assert lead["status"] == "verify_now"
