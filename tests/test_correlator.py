from gorgon_tracker.correlator import (
    BuryEvent,
    Correlator,
    LootEvent,
    SourceEvent,
    TargetSighting,
    ZoneChange,
)


def make(sec: float) -> int:
    return round(sec * 1000)


def src(sec: float, monster: str, skin=False, butcher=False, extract=False) -> SourceEvent:
    return SourceEvent(time_ms=make(sec), monster=monster, can_skin=skin, can_butcher=butcher, can_extract=extract)


def loot(sec: float, item: str, amount=1) -> LootEvent:
    return LootEvent(time_ms=make(sec), item=item, amount=amount)


def _run(correlator: Correlator, events) -> list:
    for kind, event in events:
        if kind == "zone":
            correlator.ingest_zone_change(event)
        elif kind == "target":
            correlator.ingest_target(event)
        elif kind == "loot":
            correlator.ingest_loot(event)
        elif kind == "bury":
            correlator.ingest_bury(event)
        elif kind == "source":
            correlator.ingest_source(event)
    return correlator.finalize()


def test_links_drop_to_most_recent_source() -> None:
    c = Correlator()
    drops = _run(c, [("source", src(1.0, "Rat")), ("loot", loot(3.0, "Bone")), ("source", src(4.0, "Rat"))])
    assert len(drops) == 1
    assert drops[0].source == "Rat"
    assert drops[0].status == "Linked"
    assert drops[0].lag_ms == 1000
    assert drops[0].activity == "Looting"
    assert drops[0].zone == "Unknown"


def test_orphan_uses_target_sighting() -> None:
    c = Correlator()
    drops = _run(
        c,
        [
            ("target", TargetSighting(time_ms=make(9.5), name="Dire Wolf")),
            ("loot", loot(10.0, "Pelt")),
            ("source", src(12.0, "Dire Wolf")),
        ],
    )
    assert len(drops) == 1
    assert drops[0].source == "Dire Wolf"
    assert drops[0].status == "Linked"  # linked via target, not monster
    assert drops[0].lag_ms == 500


def test_ground_orphan_when_no_source_or_target() -> None:
    c = Correlator()
    drops = _run(c, [("loot", loot(10.0, "Twig")), ("bury", BuryEvent(time_ms=make(11.0)))])
    assert len(drops) == 1
    assert drops[0].source == "Ground/Unknown"
    assert drops[0].status == "Orphaned"
    assert drops[0].lag_ms == 0


def test_retroactive_skinning() -> None:
    c = Correlator()
    drops = _run(
        c,
        [
            ("source", src(0.0, "Giant Bat", skin=True)),
            ("loot", loot(0.5, "Bat Wing")),
            ("source", src(1.0, "Giant Bat", skin=False)),
        ],
    )
    assert len(drops) == 1
    assert drops[0].activity == "Skinning"
    assert drops[0].lag_ms == 500


def test_butchering_and_extracting() -> None:
    c = Correlator()
    drops = _run(
        c,
        [
            ("source", src(0.0, "Boar", butcher=True)),
            ("loot", loot(0.2, "Bacon")),
            ("source", src(1.0, "Boar", extract=True)),
            ("loot", loot(1.2, "Skull")),
            ("source", src(2.0, "Boar")),
        ],
    )
    assert [d.activity for d in drops] == ["Butchering", "Extracting"]


def test_session_timeout_starts_new_encounter_and_resets_activity() -> None:
    c = Correlator()
    drops = _run(
        c,
        [
            ("source", src(0.0, "Rat", skin=True)),
            ("source", src(5.0, "Rat", skin=False)),  # 5s gap, 3s timeout -> new encounter
            ("loot", loot(5.5, "Bone")),
            ("source", src(6.0, "Rat")),
        ],
    )
    assert len(drops) == 1
    assert drops[0].activity == "Looting"  # no retroactive skin because new encounter
    assert drops[0].status == "Linked"


def test_skin_flag_updates_across_sources() -> None:
    c = Correlator()
    drops = _run(
        c,
        [
            ("source", src(0.0, "Rat", skin=True)),
            ("loot", loot(0.5, "Bone")),
            ("source", src(1.0, "Rat", skin=False)),
        ],
    )
    assert drops[0].activity == "Skinning"
    assert len(drops[0].encounter_uuid) == 36  # uuid4 shape


def test_bury_links_pending_drops_to_last_monster() -> None:
    c = Correlator()
    drops = _run(
        c,
        [
            ("source", src(0.0, "Rat")),
            ("loot", loot(1.0, "Bone")),
            ("loot", loot(1.5, "Pelt", 2)),
            ("bury", BuryEvent(time_ms=make(2.0))),
        ],
    )
    assert len(drops) == 2
    assert all(d.source == "Rat" and d.status == "Linked" for d in drops)
    assert [d.lag_ms for d in drops] == [1000, 500]


def test_zone_tracks_changes() -> None:
    c = Correlator()
    drops = _run(
        c,
        [
            ("zone", ZoneChange(time_ms=make(0.0), zone="Old Graveyard")),
            ("source", src(1.0, "Rat")),
            ("loot", loot(2.0, "Bone")),
            ("source", src(3.0, "Rat")),
            ("zone", ZoneChange(time_ms=make(4.0), zone="Fairy Glen")),
            ("source", src(5.0, "Wolf")),
            ("loot", loot(6.0, "Pelt")),
            ("source", src(7.0, "Wolf")),
        ],
    )
    assert [d.zone for d in drops] == ["Old Graveyard", "Fairy Glen"]


def test_finalize_flushes_pending() -> None:
    c = Correlator()
    drops = _run(c, [("source", src(0.0, "Rat")), ("loot", loot(1.0, "Bone"))])
    assert len(drops) == 1
    assert drops[0].source == "Rat"
    assert drops[0].lag_ms == 0